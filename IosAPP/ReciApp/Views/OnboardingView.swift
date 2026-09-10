import SwiftUI

struct OnboardingView: View {
    let onComplete: (UserPreferences) -> Void
    @State private var page = 0
    @State private var preferences: UserPreferences
    @State private var didComplete = false

    init(preferences: UserPreferences, onComplete: @escaping (UserPreferences) -> Void) {
        self.onComplete = onComplete
        _preferences = State(initialValue: preferences)
    }

    var body: some View {
        ZStack {
            ReciTheme.canvas
                .ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer(minLength: 0)

                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 18) {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: page == 0 ? "thermometer.medium" : "ruler")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(ReciTheme.orange)
                            .frame(width: 44, height: 44)
                            .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

                        VStack(alignment: .leading, spacing: 3) {
                            Text(ReciLocalization.string(page == 0 ? "How do you read temperatures?" : "How do you measure?"))
                                .font(.title3.weight(.bold))
                                .foregroundStyle(ReciTheme.ink)
                            Text(ReciLocalization.string(page == 0 ? "Choose your usual oven temperature unit." : "Choose the measurements that feel familiar."))
                                .font(.subheadline)
                                .foregroundStyle(ReciTheme.muted)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if page == 0 {
                        VStack(spacing: 10) {
                            ForEach(TemperatureUnit.allCases) { unit in
                                OnboardingChoiceRow(
                                    title: unit.title,
                                    detail: unit.symbol,
                                    icon: unit == .celsius ? "°C" : "°F",
                                    isSelected: preferences.temperatureUnit == unit
                                ) {
                                    preferences.temperatureUnit = unit
                                }
                            }
                        }
                    } else {
                        VStack(spacing: 10) {
                            ForEach(MeasurementSystem.allCases) { system in
                                OnboardingChoiceRow(
                                    title: system.title,
                                    detail: system.detail,
                                    icon: system == .metric ? "g" : "oz",
                                    isSelected: preferences.measurementSystem == system
                                ) {
                                    preferences.measurementSystem = system
                                }
                            }
                        }
                    }
                }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .id(page)
                    .transition(.opacity.combined(with: .move(edge: page == 0 ? .leading : .trailing)))

                    VStack(alignment: .center, spacing: 16) {
                    HStack(spacing: 8) {
                        ForEach(0..<2, id: \.self) { index in
                            Capsule()
                                .fill(index == page ? ReciTheme.orange : ReciTheme.line)
                                .frame(width: index == page ? 26 : 8, height: 8)
                        }
                    }
                    .accessibilityHidden(true)

                    if page > 0 {
                        Button("Back") {
                            ReciHaptics.selection()
                            withAnimation(.easeInOut(duration: 0.2)) {
                                page = 0
                            }
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .buttonStyle(.plain)
                    }

                    Button {
                        if page == 0 {
                            ReciHaptics.selection()
                            withAnimation(.easeInOut(duration: 0.2)) {
                                page = 1
                            }
                        } else {
                            complete()
                        }
                    } label: {
                        Text(ReciLocalization.string(page == 0 ? "Continue" : "Start cooking"))
                            .font(.headline.weight(.bold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, minHeight: 54)
                            .background(ReciTheme.orange, in: Capsule())
                    }
                    .buttonStyle(.plain)
        .accessibilityLabel(ReciLocalization.string(page == 0 ? "Continue to measurements" : "Finish onboarding"))
                }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Spacer(minLength: 0)
            }
            .padding(.horizontal, 24)
            .padding(.top, 18)
            .padding(.bottom, 20)
        }
        .interactiveDismissDisabled()
    }

    private func complete() {
        guard !didComplete else { return }
        didComplete = true
        ReciHaptics.success()
        onComplete(preferences)
    }
}

private struct OnboardingChoiceRow: View {
    let title: String
    let detail: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button {
            if !isSelected {
                ReciHaptics.selection()
            }
            action()
        } label: {
            HStack(spacing: 13) {
                Text(icon)
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(isSelected ? .white : ReciTheme.orange)
                    .frame(width: 40, height: 40)
                    .background(
                        isSelected ? ReciTheme.orange : ReciTheme.orangeSoft,
                        in: RoundedRectangle(cornerRadius: 13, style: .continuous)
                    )

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.body.weight(.semibold))
                        .foregroundStyle(ReciTheme.ink)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Spacer(minLength: 8)

                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(isSelected ? ReciTheme.orange : ReciTheme.line)
            }
            .padding(14)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title), \(detail)")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

#Preview {
    OnboardingView(preferences: UserPreferences()) { _ in }
}
