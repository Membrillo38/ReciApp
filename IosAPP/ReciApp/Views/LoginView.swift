import AuthenticationServices
import SwiftUI

struct LoginView: View {
    var playsHeroTransition = false

    @EnvironmentObject private var auth: AuthService
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @State private var nonce = ""
    @State private var toastOffset: CGFloat = 0
    @State private var signInStarted = false
    @State private var heroExpanded: Bool
    @State private var chromeVisible: Bool
    @State private var iconSlot = CGRect.zero

    init(playsHeroTransition: Bool = false) {
        self.playsHeroTransition = playsHeroTransition
        _heroExpanded = State(initialValue: playsHeroTransition)
        _chromeVisible = State(initialValue: !playsHeroTransition)
    }

    private var signInErrorMessage: String {
        ReciLocalization.string("We couldn't sign you in. Please try again.")
    }

    var body: some View {
        GeometryReader { geo in
            let mascotSize = ReciBrand.heroMascotSize(in: geo.size)
            let origin = geo.frame(in: .global)
            let hasSlot = iconSlot.width > 1
            let slotCenter = CGPoint(
                x: iconSlot.midX - origin.minX,
                y: iconSlot.midY - origin.minY
            )
            let bottomCenter = CGPoint(
                x: geo.size.width / 2,
                y: geo.size.height - mascotSize / 2
            )
            let expandOffset = (heroExpanded && hasSlot)
                ? CGSize(
                    width: bottomCenter.x - slotCenter.x,
                    height: bottomCenter.y - slotCenter.y
                )
                : .zero

            ZStack {
                ReciTheme.canvas
                ReciTheme.iconGradient(for: colorScheme)
                    .opacity(heroExpanded ? 1 : 0)

                VStack(spacing: 0) {
                    Spacer()

                    ReciAppIconView(
                        size: ReciBrand.loginIconSize,
                        plateProgress: heroExpanded ? 0 : 1
                    )
                    .scaleEffect(heroExpanded && mascotSize > 1 ? mascotSize / ReciBrand.loginIconSize : 1)
                    .offset(expandOffset)
                        .background {
                            GeometryReader { slot in
                                Color.clear.preference(
                                    key: LoginIconSlotKey.self,
                                    value: slot.frame(in: .global)
                                )
                            }
                        }
                        .zIndex(1)

                    VStack(spacing: 0) {
                        Text("Recipes worth keeping.")
                            .font(.system(size: 34, weight: .bold, design: .rounded))
                            .foregroundStyle(ReciTheme.ink)
                            .multilineTextAlignment(.center)
                            .lineSpacing(2)
                            .padding(.top, 28)

                        Text("Save recipes from your favorite videos and keep them beautifully organized.")
                            .font(.body)
                            .foregroundStyle(ReciTheme.muted)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .lineSpacing(3)
                            .padding(.horizontal, 18)
                            .padding(.top, 10)
                    }
                    .opacity(chromeVisible ? 1 : 0)
                    .offset(y: chromeVisible ? 0 : 12)

                    Spacer()

                    VStack(spacing: 0) {
                        SignInWithAppleButton(.signIn) { request in
                            signInStarted = true
                            ReciHaptics.mediumImpact()
                            nonce = UUID().uuidString
                            auth.handleAppleRequest(request, nonce: nonce)
                        } onCompletion: { result in
                            Task { await auth.handleAppleCompletion(result, nonce: nonce) }
                        }
                        .signInWithAppleButtonStyle(.black)
                        .frame(height: 54)
                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))

                        if auth.isLoading {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("Signing in…")
                            }
                            .font(.caption.weight(.medium))
                            .foregroundStyle(ReciTheme.muted)
                            .padding(.top, 12)
                        }

                        (Text("By signing you accept ")
                        + Text(.init("[\(ReciLocalization.string("privacy"))](https://example.com)"))
                            .underline()
                        + Text(" and ")
                        + Text(.init("[\(ReciLocalization.string("terms"))](https://example.com)"))
                            .underline()
                        + Text("."))
                            .font(.caption)
                            .foregroundStyle(ReciTheme.muted)
                            .tint(ReciTheme.muted)
                            .multilineTextAlignment(.center)
                            .padding(.top, 16)
                            .padding(.bottom, 12)
                    }
                    .opacity(chromeVisible ? 1 : 0)
                    .allowsHitTesting(chromeVisible)
                }
                .padding(.horizontal, 24)
                .padding(.top, geo.safeAreaInsets.top)
                .padding(.bottom, geo.safeAreaInsets.bottom)
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .onPreferenceChange(LoginIconSlotKey.self) { iconSlot = $0 }
            .overlay(alignment: .top) {
                errorToast
                    .padding(.top, geo.safeAreaInsets.top + 10)
            }
        }
        .ignoresSafeArea()
        .animation(.easeOut(duration: 0.2), value: auth.errorMessage)
        .task { await playHeroIfNeeded() }
        .onChange(of: auth.accessToken) { _, token in
            if signInStarted, token != nil {
                signInStarted = false
                ReciHaptics.success()
            }
        }
        .onChange(of: auth.errorMessage) { _, message in
            if message != nil {
                signInStarted = false
                ReciHaptics.error()
                toastOffset = 0
            }
        }
    }

    @ViewBuilder
    private var errorToast: some View {
        if auth.errorMessage != nil {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "wifi.exclamationmark")
                    .foregroundStyle(ReciTheme.orange)

                Text(signInErrorMessage)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(ReciTheme.ink)
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 13)
            .padding(.leading, 16)
            .padding(.trailing, 8)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .shadow(color: .black.opacity(0.10), radius: 16, y: 8)
            .padding(.horizontal, 20)
            .offset(y: toastOffset)
            .gesture(
                DragGesture()
                    .onChanged { value in
                        toastOffset = min(0, value.translation.height)
                    }
                    .onEnded { value in
                        if value.translation.height < -30 {
                            ReciHaptics.lightImpact()
                            withAnimation(.easeOut(duration: 0.2)) {
                                auth.dismissError()
                            }
                        } else {
                            withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) {
                                toastOffset = 0
                            }
                        }
                    }
            )
            .transition(.move(edge: .top).combined(with: .opacity))
            .task(id: auth.errorMessage) {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                withAnimation(.easeOut(duration: 0.2)) {
                    auth.dismissError()
                }
            }
        }
    }

    @MainActor
    private func playHeroIfNeeded() async {
        if !playsHeroTransition || reduceMotion {
            heroExpanded = false
            chromeVisible = true
            return
        }

        for _ in 0..<45 {
            if iconSlot.width > 1 { break }
            try? await Task.sleep(for: .milliseconds(16))
            if Task.isCancelled { return }
        }

        withAnimation(.spring(response: 0.92, dampingFraction: 0.88)) {
            heroExpanded = false
        }
        withAnimation(.easeOut(duration: 0.5).delay(0.28)) {
            chromeVisible = true
        }
    }
}

private struct LoginIconSlotKey: PreferenceKey {
    static var defaultValue = CGRect.zero

    static func reduce(value: inout CGRect, nextValue: () -> CGRect) {
        value = nextValue()
    }
}
