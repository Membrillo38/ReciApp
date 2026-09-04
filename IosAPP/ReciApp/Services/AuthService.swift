import AuthenticationServices
import CryptoKit
import Foundation
import Supabase

@MainActor
final class AuthService: ObservableObject {
    let client = SupabaseClient(
        supabaseURL: AppConfig.supabaseURL,
        supabaseKey: AppConfig.supabaseAnonKey
    )

    @Published private(set) var session: Session?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    var accessToken: String? { session?.accessToken }

    init() {
        Task {
            await restoreSession()
            await listenAuth()
        }
    }

    func restoreSession() async {
        AppLogger.auth.info("restore session started")
        do {
            session = try await client.auth.session
            AppLogger.auth.info("restore session succeeded")
        } catch {
            session = nil
            AppLogger.auth.error("restore session failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func listenAuth() async {
        for await (_, newSession) in client.auth.authStateChanges {
            session = newSession
            AppLogger.auth.info("auth state changed signedIn=\(newSession != nil, privacy: .public)")
        }
    }

    func signOut() async {
        AppLogger.auth.info("sign out started")
        try? await client.auth.signOut()
        session = nil
        AppLogger.auth.info("sign out completed")
    }

    func handleAppleRequest(_ request: ASAuthorizationAppleIDRequest, nonce: String) {
        request.requestedScopes = [.fullName, .email]
        request.nonce = sha256(nonce)
    }

    func handleAppleCompletion(_ result: Result<ASAuthorization, Error>, nonce: String) async {
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
            session = try await client.auth.signInWithIdToken(
                credentials: OpenIDConnectCredentials(
                    provider: .apple,
                    idToken: idToken,
                    nonce: nonce
                )
            )
            AppLogger.auth.info("Apple sign in succeeded")
        } catch {
            errorMessage = error.localizedDescription
            AppLogger.auth.error("Apple sign in failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
