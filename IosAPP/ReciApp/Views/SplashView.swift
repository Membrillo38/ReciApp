import SwiftUI

enum SplashDestination: Equatable {
    case home
    case login
}

enum ReciBrand {
    static let loginIconSize: CGFloat = 104

    static func heroMascotSize(in size: CGSize) -> CGFloat {
        min(size.width, size.height) * 0.5
    }
}

struct SplashView: View {
    let destination: SplashDestination?
    let onAnimationCompleted: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @State private var didComplete = false
    @State private var mascotVisible = false

    var body: some View {
        GeometryReader { proxy in
            let mascotSize = ReciBrand.heroMascotSize(in: proxy.size)

            ZStack {
                ReciTheme.iconGradient(for: colorScheme)

                ReciAppIconView(size: mascotSize, plateProgress: 0)
                    .opacity(mascotVisible ? 1 : 0)
                    .animation(
                        reduceMotion ? .easeOut(duration: 0.16) : .easeOut(duration: 0.28),
                        value: mascotVisible
                    )
                    .offset(y: mascotVisible || reduceMotion ? 0 : 72)
                    .scaleEffect(mascotVisible || reduceMotion ? 1 : 0.88)
                    .animation(
                        reduceMotion ? .easeOut(duration: 0.16) : .spring(duration: 0.72, bounce: 0.38),
                        value: mascotVisible
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .ignoresSafeArea()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("ReciApp")
        .task {
            try? await Task.sleep(for: .milliseconds(80))
            guard !Task.isCancelled else { return }
            mascotVisible = true
        }
        .task(id: destination) {
            guard destination != nil, !didComplete else { return }

            try? await Task.sleep(for: .milliseconds(reduceMotion ? 80 : 980))
            guard !Task.isCancelled else { return }
            didComplete = true
            onAnimationCompleted()
        }
    }
}

struct ReciAppIconView: View, Animatable {
    var size: CGFloat
    var plateProgress: CGFloat = 1

    @Environment(\.colorScheme) private var colorScheme

    var animatableData: CGFloat {
        get { plateProgress }
        set { plateProgress = newValue }
    }

    var body: some View {
        let progress = min(1, max(0, plateProgress))
        let mascotFactor = 1 - (1 - 0.87) * progress

        ZStack {
            ReciTheme.iconGradient(for: colorScheme)
                .opacity(progress)

            Image("SplashMascot")
                .resizable()
                .scaledToFit()
                .frame(width: size * mascotFactor, height: size * mascotFactor)
                .offset(x: -size * 0.078 * progress, y: size * 0.091 * progress)
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.26 * progress, style: .continuous))
        .shadow(color: .black.opacity(0.16 * progress), radius: 14, y: 8)
    }
}

#Preview {
    SplashView(destination: .login, onAnimationCompleted: {})
}
