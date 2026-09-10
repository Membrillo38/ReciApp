import AuthenticationServices
import CryptoKit
import Foundation
import Security

struct AuthUser: Codable, Equatable, Sendable {
    let id: UUID
    let email: String?
    let displayName: String?
    let isPro: Bool
}

struct Session: Codable, Equatable, Sendable {
    let accessToken: String
    let refreshToken: String
    let expiresAt: Date?
    let user: AuthUser

    var isNearExpiry: Bool {
        guard let expiresAt else { return false }
        return expiresAt.timeIntervalSinceNow < 60
    }
}

@MainActor
final class AuthService: ObservableObject {
    @Published private(set) var session: Session?
    @Published private(set) var isLoading = false
    @Published private(set) var hasRestoredSession = false
    @Published var errorMessage: String?

    private var refreshTasks = SharedTaskCoordinator<AuthRefreshKey, Session?, Never>()
    private var unauthorizedTokenPolicy = UnauthorizedTokenPolicy()
    private var authGeneration = 0
    private let keychain = AuthKeychainStore()
    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()
    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    var accessToken: String? { session?.accessToken }

    lazy var api: APIClient = {
        APIClient { [weak self] refresh in
            guard let service = self else { throw AppError.unauthorized }
            return try await service.bearerToken(refresh: refresh)
        }
    }()

    func dismissError() { errorMessage = nil }

    func bearerToken(refresh: Bool) async throws -> String {
        guard let current = session else { throw AppError.unauthorized }
        if refresh || current.isNearExpiry {
            let refreshed = try await refreshFromBackend(refreshToken: current.refreshToken)
            apply(refreshed)
            return refreshed.accessToken
        }
        return current.accessToken
    }

    init() {
        Task { await restoreSession() }
    }

    func restoreSession() async {
        let expectedGeneration = authGeneration
        AppLogger.auth.info("restore session started")
        do {
            let restored = try keychain.load()
            if expectedGeneration == authGeneration {
                apply(restored)
                AppLogger.auth.info("restore session succeeded")
            }
        } catch {
            let missingSession = isMissingSession(error)
            if session == nil, missingSession {
                AppLogger.auth.info("restore session: no saved session")
            } else if SessionRestorePolicy.preservesLocalSession(
                hasExistingSession: session != nil,
                missingSessionError: missingSession
            ) {
                AppLogger.auth.warning("restore session deferred; retained local session")
            } else {
                AppLogger.auth.error("restore session failed: \(error.localizedDescription, privacy: .public)")
            }
        }
        hasRestoredSession = true
    }

    @discardableResult
    func refreshSession() async -> Bool {
        guard let rejectedToken = accessToken, let userID = session?.user.id else { return false }
        return await recoverFromUnauthorized(
            rejectedToken: rejectedToken,
            expectedUserID: userID,
            expectedGeneration: authGeneration
        ) != nil
    }

    func recoveryGeneration(for expectedUserID: UUID) -> Int? {
        session?.user.id == expectedUserID ? authGeneration : nil
    }

    /// Coalesces refreshes for one rejected JWT. A second 401 for that JWT is terminal.
    func recoverFromUnauthorized(
        rejectedToken: String,
        expectedUserID: UUID,
        expectedGeneration: Int
    ) async -> String? {
        guard AuthRecoveryScopePolicy.canUseToken(
            expectedUserID: expectedUserID,
            expectedGeneration: expectedGeneration,
            currentUserID: session?.user.id,
            currentGeneration: authGeneration
        ) else { return nil }
        if let currentToken = accessToken, currentToken != rejectedToken { return currentToken }
        let refreshKey = AuthRefreshKey(
            rejectedToken: rejectedToken,
            userID: expectedUserID,
            generation: expectedGeneration
        )
        if let entry = refreshTasks.entry(for: refreshKey) {
            return await resolvedRefresh(entry, key: refreshKey)
        }
        guard unauthorizedTokenPolicy.canStartRefresh(for: rejectedToken) else {
            await invalidateSession(expectedUserID: expectedUserID, rejectedToken: rejectedToken)
            return nil
        }
        // Consume before starting so cancellation or invalidation cannot reopen this JWT.
        unauthorizedTokenPolicy.finishRefresh(for: rejectedToken)

        let entry = refreshTasks.acquire(for: refreshKey) {
            Task<Session?, Never> {
                do {
                    guard let refreshToken = await self.session?.refreshToken else { return nil }
                    let refreshed = try await self.refreshFromBackend(refreshToken: refreshToken)
                    return Task.isCancelled ? nil : refreshed
                } catch {
                    AppLogger.auth.error("session refresh failed: \(error.localizedDescription, privacy: .public)")
                    return nil
                }
            }
        }
        return await resolvedRefresh(entry, key: refreshKey)
    }

    private func resolvedRefresh(
        _ entry: SharedTaskCoordinator<AuthRefreshKey, Session?, Never>.Entry,
        key: AuthRefreshKey
    ) async -> String? {
        let refreshed = await entry.task.value
        refreshTasks.release(key: key, id: entry.id)
        guard AuthRecoveryScopePolicy.canUseToken(
            expectedUserID: key.userID,
            expectedGeneration: key.generation,
            currentUserID: session?.user.id,
            currentGeneration: authGeneration
        ) else { return nil }
        guard let refreshed, refreshed.accessToken != key.rejectedToken else {
            await invalidateSession(expectedUserID: key.userID, rejectedToken: key.rejectedToken)
            return nil
        }
        guard refreshed.user.id == key.userID else { return nil }
        apply(refreshed)
        AppLogger.auth.info("session refresh succeeded")
        return refreshed.accessToken
    }

    func signOut() async {
        AppLogger.auth.info("sign out started")
        let refreshToken = session?.refreshToken
        await LogoutOrderingPolicy.clearBeforeRemote(
            clear: { self.clearSession() },
            remote: {
                guard let refreshToken else { return }
                try? await self.logout(refreshToken: refreshToken)
            }
        )
        AppLogger.auth.info("sign out completed")
    }

    func invalidateSession(expectedUserID: UUID, rejectedToken: String) async {
        guard session?.user.id == expectedUserID, accessToken == rejectedToken else { return }
        await signOut()
    }

    func handleAppleRequest(_ request: ASAuthorizationAppleIDRequest, nonce: String) {
        request.requestedScopes = [.fullName, .email]
        request.nonce = sha256(nonce)
    }

    func handleAppleCompletion(_ result: Result<ASAuthorization, Error>, nonce: String) async {
        let expectedGeneration = authGeneration
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let credential = try result.get()
            guard let apple = credential.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = apple.identityToken,
                  let idToken = String(data: tokenData, encoding: .utf8) else {
                throw AppError.server("Invalid Apple credential")
            }
            let signedIn = try await signInWithApple(
                identityToken: idToken,
                nonce: nonce,
                fullName: formattedName(apple.fullName)
            )
            guard expectedGeneration == authGeneration else { return }
            apply(signedIn)
            AppLogger.auth.info("Apple sign in succeeded")
        } catch {
            errorMessage = error.localizedDescription
            AppLogger.auth.error("Apple sign in failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func apply(_ newSession: Session) {
        if session?.user.id != newSession.user.id {
            authGeneration += 1
        }
        session = newSession
        do {
            try keychain.save(newSession)
        } catch {
            AppLogger.auth.error("session save failed: \(error.localizedDescription, privacy: .public)")
        }
        SubscriptionService.shared.identify(userID: newSession.user.id)
    }

    private func clearSession() {
        authGeneration += 1
        session = nil
        refreshTasks.cancelAll()
        keychain.clear()
        SubscriptionService.shared.reset()
    }

    private func isMissingSession(_ error: Error) -> Bool {
        if case AuthKeychainStore.StoreError.missing = error { return true }
        return error.localizedDescription.localizedCaseInsensitiveContains("Auth session missing")
    }

    private func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func formattedName(_ components: PersonNameComponents?) -> String? {
        guard let components else { return nil }
        let value = PersonNameComponentsFormatter().string(from: components).trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private func signInWithApple(identityToken: String, nonce: String, fullName: String?) async throws -> Session {
        let payload = AppleAuthRequest(identityToken: identityToken, nonce: nonce, fullName: fullName)
        let response: AuthTokenResponse = try await post("v1/auth/apple", body: payload)
        return try makeSession(from: response, fallbackUser: nil)
    }

    private func refreshFromBackend(refreshToken: String) async throws -> Session {
        let response: AuthTokenResponse = try await post("v1/auth/refresh", body: RefreshAuthRequest(refreshToken: refreshToken))
        return try makeSession(from: response, fallbackUser: session?.user)
    }

    private func logout(refreshToken: String) async throws {
        let _: OkResponse = try await post("v1/auth/logout", body: RefreshAuthRequest(refreshToken: refreshToken))
    }

    private func makeSession(from response: AuthTokenResponse, fallbackUser: AuthUser?) throws -> Session {
        guard response.tokenType.lowercased() == "bearer" else { throw AppError.server("Unsupported auth token") }
        guard let user = response.user ?? fallbackUser else { throw AppError.server("Missing auth user") }
        return Session(
            accessToken: response.accessToken,
            refreshToken: response.refreshToken,
            expiresAt: Date().addingTimeInterval(TimeInterval(response.expiresIn)),
            user: user
        )
    }

    private func post<Request: Encodable, Response: Decodable>(_ path: String, body: Request) async throws -> Response {
        let url = AppConfig.apiBaseURL.appending(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AppError.server("No response") }
        if http.statusCode == 401 { throw AppError.unauthorized }
        guard (200...299).contains(http.statusCode) else {
            let parsed = APIErrorDetailParser.parse(data: data, status: http.statusCode)
            throw AppError.server(parsed.message)
        }
        return try decoder.decode(Response.self, from: data)
    }
}

private struct AppleAuthRequest: Encodable {
    let identityToken: String
    let nonce: String
    let fullName: String?
}

private struct RefreshAuthRequest: Encodable {
    let refreshToken: String
}

private struct AuthTokenResponse: Decodable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresIn: Int
    let user: AuthUser?
}

private struct AuthKeychainStore {
    enum StoreError: Error {
        case missing
        case unhandled(OSStatus)
    }

    private let service = "com.membri.reciapp.auth"
    private let account = "session"

    func load() throws -> Session {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { throw StoreError.missing }
        guard status == errSecSuccess else { throw StoreError.unhandled(status) }
        guard let data = result as? Data else { throw StoreError.missing }
        return try JSONDecoder().decode(Session.self, from: data)
    }

    func save(_ session: Session) throws {
        let data = try JSONEncoder().encode(session)
        var query = baseQuery()
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecSuccess { return }
        if status == errSecItemNotFound {
            query.merge(attributes) { _, new in new }
            let addStatus = SecItemAdd(query as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw StoreError.unhandled(addStatus) }
            return
        }
        throw StoreError.unhandled(status)
    }

    func clear() {
        SecItemDelete(baseQuery() as CFDictionary)
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }
}
