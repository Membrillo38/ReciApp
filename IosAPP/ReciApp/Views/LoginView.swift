import AuthenticationServices
import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var auth: AuthService
    @State private var nonce = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("ReciApp")
            Text("Sign in with Apple to continue")
            SignInWithAppleButton(.signIn) { request in
                nonce = UUID().uuidString
                auth.handleAppleRequest(request, nonce: nonce)
            } onCompletion: { result in
                Task { await auth.handleAppleCompletion(result, nonce: nonce) }
            }
            .frame(height: 44)
            if auth.isLoading { Text("Signing in…") }
            if let err = auth.errorMessage { Text(err) }
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}
