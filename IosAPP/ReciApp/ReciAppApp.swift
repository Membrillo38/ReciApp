import SwiftUI

@main
struct ReciAppApp: App {
    @StateObject private var auth = AuthService()
    @StateObject private var app = AppViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(app)
                .tint(Color(red: 1, green: 0.329, blue: 0))
                .onAppear { app.bind(auth: auth) }
                .onOpenURL { url in
                    Task { await app.importFromRaw(url.absoluteString) }
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var auth: AuthService
    @EnvironmentObject private var app: AppViewModel

    var body: some View {
        Group {
            if auth.accessToken != nil {
                HomeView()
                    .task {
                        await app.refreshAll()
                        await app.flushPendingImport()
                    }
            } else {
                LoginView()
            }
        }
    }
}
