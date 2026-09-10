import SwiftUI
import UIKit

enum ReciTheme {
    static let canvas = Color(hex: "F7F7FA")
    static let surface = Color(hex: "FFFFFF")
    static let ink = Color(hex: "202126")
    static let muted = Color(hex: "74757D")
    static let line = Color(hex: "E9E9EF")
    static let orange = Color(hex: "FF6240")
    static let orangeSoft = Color(hex: "FFE9E2")
    static let green = Color(hex: "4F7E6B")

    static func iconGradient(for colorScheme: ColorScheme) -> LinearGradient {
        LinearGradient(
            colors: colorScheme == .dark
                ? [Color(hex: "627FFF"), Color(hex: "000087")]
                : [Color(hex: "74C4FF"), Color(hex: "0088FF")],
            startPoint: .top,
            endPoint: UnitPoint(x: 0.5, y: 0.72)
        )
    }
}

extension Color {
    init(hex: String) {
        let clean = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        let value = UInt64(clean, radix: 16) ?? 0
        self.init(
            red: Double((value >> 16) & 0xFF) / 255,
            green: Double((value >> 8) & 0xFF) / 255,
            blue: Double(value & 0xFF) / 255
        )
    }

    var hexString: String {
        let color = UIColor(self)
        var red: CGFloat = 0
        var green: CGFloat = 0
        var blue: CGFloat = 0
        color.getRed(&red, green: &green, blue: &blue, alpha: nil)
        return String(format: "%02X%02X%02X", Int(red * 255), Int(green * 255), Int(blue * 255))
    }
}

enum ReciHaptics {
    static let enabledDefaultsKey = "reciapp.haptics.enabled.v1"

    private static let selectionGenerator = UISelectionFeedbackGenerator()
    private static let lightImpactGenerator = UIImpactFeedbackGenerator(style: .light)
    private static let mediumImpactGenerator = UIImpactFeedbackGenerator(style: .medium)
    private static let notificationGenerator = UINotificationFeedbackGenerator()

    private static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: enabledDefaultsKey) as? Bool ?? true
    }

    static func selection() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        selectionGenerator.prepare()
        selectionGenerator.selectionChanged()
    }

    static func lightImpact() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        lightImpactGenerator.prepare()
        lightImpactGenerator.impactOccurred()
    }

    static func mediumImpact() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        mediumImpactGenerator.prepare()
        mediumImpactGenerator.impactOccurred()
    }

    static func success() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        notificationGenerator.prepare()
        notificationGenerator.notificationOccurred(.success)
    }

    static func warning() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        notificationGenerator.prepare()
        notificationGenerator.notificationOccurred(.warning)
    }

    static func error() {
        guard isEnabled, !UIAccessibility.isReduceMotionEnabled else { return }
        notificationGenerator.prepare()
        notificationGenerator.notificationOccurred(.error)
    }
}

struct ReciIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .frame(width: 44, height: 44)
            .background(ReciTheme.surface.opacity(configuration.isPressed ? 0.72 : 0.96))
            .clipShape(Circle())
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.spring(response: 0.24, dampingFraction: 0.76), value: configuration.isPressed)
    }
}

@main
struct ReciAppApp: App {
    @StateObject private var auth = AuthService()
    @StateObject private var app = AppViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(app)
                .fontDesign(.rounded)
                .tint(ReciTheme.orange)
                .onAppear {
                    app.bind(auth: auth)
                    SubscriptionService.shared.configure()
                }
                .onOpenURL { url in
                    Task { await app.importFromIncomingURL(url) }
                }
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var auth: AuthService
    @EnvironmentObject private var app: AppViewModel
    @AppStorage(AppLanguageStore.storageKey) private var languageRawValue = AppLanguage.system.rawValue
    @State private var splashAnimationFinished = false
    @State private var authResolutionReady = false
    @State private var showOnboarding = false
    @State private var playLoginHero = true
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var isDesignPreview: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("-reciapp-design-preview")
        #else
        false
        #endif
    }

    private var isOnboardingPreview: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("-reciapp-onboarding-preview")
        #else
        false
        #endif
    }

    private var isSettingsPreview: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("-reciapp-settings-preview")
        #else
        false
        #endif
    }

    private var isSplashPreview: Bool {
        #if DEBUG
        ProcessInfo.processInfo.arguments.contains("-reciapp-splash-preview")
        #else
        false
        #endif
    }

    private var launchReady: Bool {
        splashAnimationFinished && authResolutionReady
    }

    private var splashDestination: SplashDestination? {
        guard authResolutionReady else { return nil }
        return auth.accessToken == nil ? .login : .home
    }

    private var authenticatedUserID: String? {
        auth.session?.user.id.uuidString
    }

    private var selectedLanguage: AppLanguage {
        AppLanguageStore.selection
    }

    var body: some View {
        Group {
            if isSplashPreview {
                SplashView(destination: .login, onAnimationCompleted: {})
            } else if isSettingsPreview {
                ProfileView()
            } else if isOnboardingPreview {
                OnboardingView(preferences: UserPreferences()) { _ in }
            } else if isDesignPreview {
                HomeView()
                    .task { app.loadDesignPreview() }
            } else if !launchReady {
                SplashView(destination: splashDestination) {
                    splashAnimationFinished = true
                }
                .transition(
                    .asymmetric(
                        insertion: .identity,
                        removal: splashDestination == .login ? .identity : .opacity
                    )
                )
            } else if auth.accessToken != nil {
                HomeView()
            } else {
                LoginView(playsHeroTransition: playLoginHero && !reduceMotion)
                    .onDisappear { playLoginHero = false }
            }
        }
        .animation(
            splashDestination == .login
                ? nil
                : (reduceMotion ? .easeOut(duration: 0.15) : .easeOut(duration: 0.36)),
            value: launchReady
        )
        .task {
            await app.warmUpBackend()
        }
        .environment(\.locale, Locale(identifier: selectedLanguage.localeIdentifier))
        .task(id: auth.hasRestoredSession) {
            guard !authResolutionReady else { return }
            if auth.hasRestoredSession {
                authResolutionReady = true
                return
            }
            do { try await Task.sleep(for: .milliseconds(750)) }
            catch { return }
            guard !Task.isCancelled, !authResolutionReady else { return }
            // Never leave the app on an indefinite splash when auth provider is slow.
            authResolutionReady = true
        }
        .task(id: "\(launchReady)-\(auth.hasRestoredSession)-\(authenticatedUserID ?? "")") {
            guard launchReady, !isDesignPreview, !isOnboardingPreview, !isSettingsPreview, auth.hasRestoredSession else { return }

            guard let userID = authenticatedUserID else {
                showOnboarding = false
                return
            }

            showOnboarding = !UserPreferencesStore.isComplete(for: userID)
        }
        .task(id: "\(auth.hasRestoredSession)-\(authenticatedUserID ?? "signed-out")-\(selectedLanguage.serverCode)") {
            guard auth.hasRestoredSession, !isDesignPreview, !isSettingsPreview else { return }
            guard let userID = auth.session?.user.id, auth.accessToken != nil else {
                app.sessionDidEnd()
                return
            }
            app.activate(userID: userID, language: selectedLanguage.serverCode)
            await app.refreshAll()
            await app.flushPendingImport()
        }
        .onChange(of: "\(auth.hasRestoredSession)-\(authenticatedUserID ?? "signed-out")-\(selectedLanguage.serverCode)") { _, _ in
            guard auth.hasRestoredSession, !isDesignPreview, !isSettingsPreview else { return }
            if let userID = auth.session?.user.id, auth.accessToken != nil {
                // Cache activation is synchronous; network refresh happens in the task above.
                app.activate(userID: userID, language: selectedLanguage.serverCode)
            } else {
                app.sessionDidEnd()
            }
        }
        .onChange(of: app.errorMessage) { _, message in
            if message != nil {
                ReciHaptics.error()
            }
        }
        .onChange(of: app.lastImportedRecipe?.id) { _, recipeID in
            if recipeID != nil {
                ReciHaptics.success()
            }
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active, auth.accessToken != nil, !isDesignPreview, !isSettingsPreview else { return }
            Task {
                await app.refreshForForeground()
                await app.drainShareInbox()
                await app.resumePersistedJobIfNeeded()
            }
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingView(preferences: UserPreferences()) { preferences in
                guard let userID = authenticatedUserID else {
                    showOnboarding = false
                    return
                }

                UserPreferencesStore.save(preferences, for: userID)
                showOnboarding = false
            }
        }
    }
}
