import AuthenticationServices
import CryptoKit
import Foundation
import Supabase

@MainActor
final class AuthService: ObservableObject {
    let client = SupabaseClient(
        supabaseURL: AppConfig.supabaseURL,
        supabaseKey: AppConfig.supabaseAnonKey,
        options: SupabaseClientOptions(auth: .init(emitLocalSessionAsInitialSession: true))
    )

    @Published private(set) var session: Session?
    @Published private(set) var isLoading = false
    @Published private(set) var hasRestoredSession = false
    @Published var errorMessage: String?

    private var refreshTasks = SharedTaskCoordinator<AuthRefreshKey, Session?, Never>()
    private var unauthorizedTokenPolicy = UnauthorizedTokenPolicy()
    private var authGeneration = 0

    var accessToken: String? { session?.accessToken }

    lazy var api: APIClient = {
        APIClient { [weak self] refresh in
            guard let service = self else { throw AppError.unauthorized }
            return try await service.bearerToken(refresh: refresh)
        }
    }()

    func dismissError() { errorMessage = nil }

    func bearerToken(refresh: Bool) async throws -> String {
        if refresh {
            let refreshed = try await client.auth.refreshSession()
            apply(refreshed)
            return refreshed.accessToken
        }
        let live = try await client.auth.session
        if session?.accessToken != live.accessToken {
            apply(live)
        }
        return live.accessToken
    }

    init() {
        Task { await listenAuth() }
        Task { await restoreSession() }
    }

    func restoreSession() async {
        let expectedGeneration = authGeneration
        AppLogger.auth.info("restore session started")
        do {
            let restored = try await client.auth.session
            if expectedGeneration == authGeneration {
                apply(restored)
                AppLogger.auth.info("restore session succeeded")
            }
        } catch {
            // Keep a session already emitted from local storage when refresh is offline.
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

        let client = client
        let entry = refreshTasks.acquire(for: refreshKey) {
            Task<Session?, Never> {
                do {
                    let refreshed = try await client.auth.refreshSession()
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

    private func listenAuth() async {
        for await (event, newSession) in client.auth.authStateChanges {
            if event == .initialSession, newSession?.isExpired == true {
                AppLogger.auth.info("ignored expired initial session")
                continue
            }
            if let newSession {
                apply(newSession)
            } else {
                clearSession()
            }
            hasRestoredSession = true
            AppLogger.auth.info("auth state changed signedIn=\(newSession != nil, privacy: .public)")
        }
    }

    func signOut() async {
        AppLogger.auth.info("sign out started")
        await LogoutOrderingPolicy.clearBeforeRemote(
            clear: { self.clearSession() },
            remote: { _ = try? await self.client.auth.signOut(scope: .local) }
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
            let signedIn = try await client.auth.signInWithIdToken(
                credentials: OpenIDConnectCredentials(
                    provider: .apple,
                    idToken: idToken,
                    nonce: nonce
                )
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
        SubscriptionService.shared.identify(userID: newSession.user.id)
    }

    private func clearSession() {
        authGeneration += 1
        session = nil
        refreshTasks.cancelAll()
        SubscriptionService.shared.reset()
    }

    private func isMissingSession(_ error: Error) -> Bool {
        error.localizedDescription.localizedCaseInsensitiveContains("Auth session missing")
    }

    private func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
