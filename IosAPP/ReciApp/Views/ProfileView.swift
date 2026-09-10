import SwiftUI

struct ProfileView: View {
    @EnvironmentObject private var auth: AuthService
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirmDelete = false
    @State private var confirmDeleteFolders = false
    @State private var errorToastOffset: CGFloat = 0
    @State private var developerDetailsExpanded = false
    @State private var preferences = UserPreferences()
    @State private var preferencesLoaded = false
    @State private var isRestoringPurchases = false
    @AppStorage(AppLanguageStore.storageKey) private var languageRawValue = AppLanguage.system.rawValue
    @AppStorage(ReciHaptics.enabledDefaultsKey) private var hapticsEnabled = true

    private var preferenceUserID: String? {
        auth.session?.user.id.uuidString
    }

    var body: some View {
        NavigationStack {
            ZStack {
                ReciTheme.canvas.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 14) {
                        accountCard
                        usageCard
                        recipePreferencesCard
                        folderLayoutCard
                        actionsCard
                        aboutSection
                        developerCard
                    }
                    .padding(20)
                }
                .scrollIndicators(.hidden)

                if app.errorMessage != nil {
                    VStack {
                        profileErrorToast
                        Spacer()
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
            .animation(.easeOut(duration: 0.2), value: app.errorMessage)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(ReciTheme.canvas, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                        .fontWeight(.semibold)
                }
            }
            .task(id: preferenceUserID) {
                loadPreferences()
            }
            .onChange(of: preferences) { _, newValue in
                guard preferencesLoaded, let preferenceUserID else { return }
                UserPreferencesStore.save(newValue, for: preferenceUserID)
            }
            .alert("Delete account?", isPresented: $confirmDelete) {
                Button("Delete", role: .destructive) {
                    ReciHaptics.warning()
                    Task { await deleteAccount() }
                }
                Button("Cancel", role: .cancel) {
                    ReciHaptics.lightImpact()
                }
            } message: {
                Text("This signs you out and requests account deletion. ReciApp removes this account's recipes. Complete removal from every provider can take additional review.")
            }
            .alert("Delete all folders?", isPresented: $confirmDeleteFolders) {
                Button("Delete folders", role: .destructive) {
                    ReciHaptics.warning()
                    app.deleteAllCustomCategories()
                    ReciHaptics.success()
                }
                Button("Cancel", role: .cancel) {
                    ReciHaptics.lightImpact()
                }
            } message: {
                Text("Recipes remain saved and move to Uncategorized.")
            }
        }
    }

    private var accountCard: some View {
        HStack(spacing: 15) {
            ZStack {
                Circle()
                    .fill(ReciTheme.orangeSoft)
                    .frame(width: 58, height: 58)
                Image(systemName: "person.fill")
                    .font(.system(size: 22, weight: .medium))
                    .foregroundStyle(ReciTheme.orange)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(app.me?.displayName ?? ReciLocalization.string("Your account"))
                    .font(.title3.weight(.bold))
                    .foregroundStyle(ReciTheme.ink)
                Text("\(app.planLabel) \(ReciLocalization.string("plan"))")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
            }

            Spacer()

            Text(app.planLabel)
                .font(.caption.weight(.bold))
                .foregroundStyle(app.me?.isPro == true ? ReciTheme.green : ReciTheme.orange)
                .padding(.horizontal, 11)
                .padding(.vertical, 7)
                .background(
                    (app.me?.isPro == true ? ReciTheme.green : ReciTheme.orange)
                        .opacity(0.12),
                    in: Capsule()
                )
        }
        .padding(17)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }

    private var profileErrorToast: some View {
        HStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(ReciTheme.orange)
            Text(app.errorMessage ?? ReciLocalization.string("We couldn't complete that action. Please try again."))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(ReciTheme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 13)
        .padding(.horizontal, 16)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .shadow(color: .black.opacity(0.10), radius: 16, y: 8)
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .offset(y: errorToastOffset)
        .gesture(
            DragGesture()
                .onChanged { value in
                    errorToastOffset = min(0, value.translation.height)
                }
                .onEnded { value in
                    if value.translation.height < -30 {
                        ReciHaptics.lightImpact()
                        withAnimation(.easeOut(duration: 0.2)) { app.dismissError() }
                    } else {
                        withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) { errorToastOffset = 0 }
                    }
                }
        )
        .transition(.move(edge: .top).combined(with: .opacity))
        .task(id: app.errorMessage) {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.2)) { app.dismissError() }
        }
    }

    @ViewBuilder
    private var usageCard: some View {
        if let me = app.me {
            VStack(alignment: .leading, spacing: 15) {
                HStack {
                    Text("Weekly imports")
                        .font(.headline)
                        .foregroundStyle(ReciTheme.ink)
                    Spacer()
                    Text("\(me.freeRemaining) \(ReciLocalization.string("left"))")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ReciTheme.muted)
                }

                GeometryReader { proxy in
                    ZStack(alignment: .leading) {
                        Capsule().fill(ReciTheme.line)
                        Capsule()
                            .fill(ReciTheme.orange)
                            .frame(width: proxy.size.width * usageProgress(me))
                    }
                }
                .frame(height: 8)

                Text(String(format: ReciLocalization.string("%d of %d free recipes used"), me.freeUsedThisWeek, me.freeLimit))
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)

                if !me.isPro {
                    Button {
                        ReciHaptics.mediumImpact()
                        SubscriptionService.shared.presentUpgrade { [weak app] in
                            Task { @MainActor in
                                await app?.refreshSubscriptionState()
                            }
                        }
                    } label: {
                        HStack {
                            Text("Upgrade to Pro")
                            Spacer()
                            Image(systemName: "arrow.up.right")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.orange)
                        .padding(.top, 2)
                    }
                    .buttonStyle(.plain)
                }

                Button {
                    guard !isRestoringPurchases else { return }
                    ReciHaptics.lightImpact()
                    isRestoringPurchases = true
                    SubscriptionService.shared.restorePurchases { [weak app] restored in
                        Task { @MainActor in
                            isRestoringPurchases = false
                            if restored {
                                await app?.refreshSubscriptionState()
                            } else {
                                app?.errorMessage = ReciLocalization.string("We couldn't complete that action. Please try again.")
                            }
                        }
                    }
                } label: {
                    HStack {
                        Text("Restore purchases")
                        Spacer()
                        if isRestoringPurchases {
                            ProgressView()
                                .tint(ReciTheme.muted)
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.muted)
                    .padding(.top, 2)
                }
                .buttonStyle(.plain)
                .disabled(isRestoringPurchases)
            }
            .padding(17)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        }
    }

    private var recipePreferencesCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SettingsSectionHeader(
                icon: "slider.horizontal.3",
                title: "Preferences",
                subtitle: "Your recipe defaults."
            )

            SettingsSegmentedRow(
                icon: "scalemass",
                title: "Measurements",
                subtitle: preferences.measurementSystem.detail,
                options: MeasurementSystem.allCases,
                selection: measurementBinding,
                label: { $0.title }
            )

            SettingsSegmentedRow(
                icon: "thermometer.medium",
                title: "Temperature",
                subtitle: "Oven temperature unit",
                options: TemperatureUnit.allCases,
                selection: temperatureBinding,
                label: { $0.symbol }
            )

            SettingsMenuRow(
                icon: "globe",
                title: "Language",
                subtitle: selectedLanguage.displayName,
                options: [AppLanguage.system] + AppLanguage.supportedLanguages,
                selection: languageBinding,
                label: { $0.displayName }
            )

            HapticSettingsRow(isEnabled: $hapticsEnabled)
        }
        .padding(16)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }

    private var folderLayoutCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SettingsSectionHeader(
                icon: "folder",
                title: "Folders",
                subtitle: "Home layout and organization."
            )

            SettingsSegmentedRow(
                icon: "folder",
                title: "Folder layout",
                subtitle: "Choose grid or list independently.",
                options: CollectionLayout.allCases,
                selection: folderLayoutBinding,
                label: { $0.title }
            )

            SettingsSegmentedRow(
                icon: "fork.knife",
                title: "Recipe layout",
                subtitle: "Choose grid or list independently.",
                options: CollectionLayout.allCases,
                selection: recipeLayoutBinding,
                label: { $0.title }
            )

            SettingsMenuRow(
                icon: "arrow.up.arrow.down",
                title: "Folder order",
                subtitle: currentFolderSort.title,
                options: FolderSort.allCases,
                selection: folderSortBinding,
                label: { $0.title }
            )

            SettingsSegmentedRow(
                icon: "rectangle.split.3x1",
                title: "Cards per row",
                subtitle: "Choose how much fits on Home.",
                options: [1, 2, 3],
                selection: folderColumnsBinding,
                label: { "\($0)" }
            )

            if currentFolderSort != .created || app.folderColumns != 2
                || currentFolderLayout != .grid || currentRecipeLayout != .grid {
                Button {
                    resetFolderLayout()
                } label: {
                    Label("Reset layout", systemImage: "arrow.counterclockwise")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.orange)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(ReciTheme.orangeSoft, in: Capsule())
                }
                .buttonStyle(.plain)
            }
            SettingsRow(icon: "folder.badge.minus", title: "Delete custom folders", tint: .red) {
                ReciHaptics.warning()
                confirmDeleteFolders = true
            }
        }
        .padding(16)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }

    private var actionsCard: some View {
        VStack(alignment: .leading, spacing: 4) {
            SettingsSectionHeader(
                icon: "person.crop.circle",
                title: "Account",
                subtitle: "Sync and account actions."
            )
            .padding(.horizontal, 16)
            .padding(.top, 16)

            SettingsRow(icon: "arrow.clockwise", title: "Refresh recipes", tint: ReciTheme.green) {
                Task { await refreshRecipes() }
            }
            SettingsRow(icon: "rectangle.portrait.and.arrow.right", title: "Sign out", tint: ReciTheme.orange) {
                ReciHaptics.mediumImpact()
                Task {
                    await auth.signOut()
                    ReciHaptics.success()
                }
            }
            SettingsRow(icon: "trash", title: "Delete account", tint: .red) {
                ReciHaptics.warning()
                confirmDelete = true
            }
        }
        .padding(.bottom, 8)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
    }

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            SettingsSectionHeader(
                icon: "info.circle",
                title: "About ReciApp",
                subtitle: "Your recipes stay synced to your account."
            )

            SettingsInfoRow(icon: "app.badge", title: "Version", value: appVersion)
            SettingsInfoRow(icon: "checkmark.shield", title: "Preferences", value: "Saved to your account")
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 6)
    }

    private var currentFolderSort: FolderSort {
        FolderSort(rawValue: app.folderSortRawValue) ?? .created
    }

    private var currentFolderLayout: CollectionLayout {
        CollectionLayout(rawValue: app.folderLayoutRawValue) ?? .grid
    }

    private var currentRecipeLayout: CollectionLayout {
        CollectionLayout(rawValue: app.recipeLayoutRawValue) ?? .grid
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"
        return String(format: "%@ (%@)", version, build)
    }

    private var measurementBinding: Binding<MeasurementSystem> {
        Binding(
            get: { preferences.measurementSystem },
            set: { newValue in
                guard preferences.measurementSystem != newValue else { return }
                preferences.measurementSystem = newValue
                ReciHaptics.selection()
            }
        )
    }

    private var temperatureBinding: Binding<TemperatureUnit> {
        Binding(
            get: { preferences.temperatureUnit },
            set: { newValue in
                guard preferences.temperatureUnit != newValue else { return }
                preferences.temperatureUnit = newValue
                ReciHaptics.selection()
            }
        )
    }

    private var selectedLanguage: AppLanguage {
        AppLanguageStore.selection
    }

    private var languageBinding: Binding<AppLanguage> {
        Binding(
            get: { selectedLanguage },
            set: { newValue in
                guard newValue != selectedLanguage else { return }
                ReciHaptics.selection()
                AppLanguageStore.selection = newValue
                languageRawValue = newValue.rawValue
                Task { await app.refreshAll() }
            }
        )
    }

    private var folderSortBinding: Binding<FolderSort> {
        Binding(
            get: { currentFolderSort },
            set: { newValue in
                guard currentFolderSort != newValue else { return }
                app.updateFolderDisplayPreferences(sort: newValue)
                ReciHaptics.selection()
            }
        )
    }

    private var folderColumnsBinding: Binding<Int> {
        Binding(
            get: { app.folderColumns },
            set: { newValue in
                guard app.folderColumns != newValue else { return }
                app.updateFolderDisplayPreferences(columns: newValue)
                ReciHaptics.selection()
            }
        )
    }

    private var folderLayoutBinding: Binding<CollectionLayout> {
        Binding(
            get: { currentFolderLayout },
            set: { newValue in
                guard currentFolderLayout != newValue else { return }
                app.updateFolderDisplayPreferences(folderLayout: newValue)
                ReciHaptics.selection()
            }
        )
    }

    private var recipeLayoutBinding: Binding<CollectionLayout> {
        Binding(
            get: { currentRecipeLayout },
            set: { newValue in
                guard currentRecipeLayout != newValue else { return }
                app.updateFolderDisplayPreferences(recipeLayout: newValue)
                ReciHaptics.selection()
            }
        )
    }

    private func loadPreferences() {
        preferencesLoaded = false
        guard let preferenceUserID else {
            preferences = UserPreferences()
            preferencesLoaded = true
            return
        }
        preferences = UserPreferencesStore.load(for: preferenceUserID) ?? UserPreferences()
        preferencesLoaded = true
    }

    private func resetFolderLayout() {
        guard currentFolderSort != .created || app.folderColumns != 2
            || currentFolderLayout != .grid || currentRecipeLayout != .grid else { return }
        ReciHaptics.lightImpact()
        withAnimation(.easeInOut(duration: 0.2)) {
            app.resetFolderDisplayPreferences()
        }
    }

    @ViewBuilder
    private var developerCard: some View {
        #if DEBUG
        VStack(spacing: 12) {
            DisclosureGroup(isExpanded: $developerDetailsExpanded) {
                VStack(alignment: .leading, spacing: 9) {
                    Text("Auto Pro: \(DevConfig.autoGrantPro ? "On" : "Off")")
                    if let me = app.me {
                        Text("Account ID: \(me.id.uuidString)")
                            .textSelection(.enabled)
                    }
                }
                .font(.caption)
                .foregroundStyle(ReciTheme.muted)
                .padding(.top, 12)
            } label: {
                Label("Developer details", systemImage: "hammer")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.ink)
            }
            .tint(ReciTheme.muted)
            .padding(17)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
            .onChange(of: developerDetailsExpanded) { _, _ in
                ReciHaptics.selection()
            }

            Button {
                ReciHaptics.mediumImpact()
                app.createDebugColorFolders()
            } label: {
                Label("Create debug color folders", systemImage: "swatchpalette")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
            .buttonStyle(.plain)

            Button {
                ReciHaptics.mediumImpact()
                app.createDebugMaxLengthFolders()
            } label: {
                Label("Create max-length test folders", systemImage: "textformat.size")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
            .buttonStyle(.plain)

            Button {
                ReciHaptics.mediumImpact()
                app.createDebugRecipesPerFolder()
            } label: {
                Label("Add 3–9 test recipes to every folder", systemImage: "fork.knife")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
            .buttonStyle(.plain)

            Button {
                ReciHaptics.mediumImpact()
                app.createDebugPerformanceData()
            } label: {
                Label("Create performance test data", systemImage: "speedometer")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
            .buttonStyle(.plain)

            Button {
                ReciHaptics.warning()
                confirmDeleteFolders = true
            } label: {
                Label("Delete all debug folders", systemImage: "trash")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(17)
                    .background(.red.opacity(0.10), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
            .buttonStyle(.plain)
        }
        #else
        EmptyView()
        #endif
    }

    private func usageProgress(_ me: MeResponse) -> CGFloat {
        guard me.freeLimit > 0 else { return 0 }
        return min(max(CGFloat(me.freeUsedThisWeek) / CGFloat(me.freeLimit), 0), 1)
    }

    private func refreshRecipes() async {
        ReciHaptics.lightImpact()
        await app.refreshAll()
        if app.errorMessage == nil {
            ReciHaptics.success()
        }
    }

    private func deleteAccount() async {
        await app.deleteAccount()
        if app.errorMessage == nil {
            ReciHaptics.success()
        }
    }
}

private struct SettingsRow: View {
    let icon: String
    let title: String
    let tint: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 13) {
                Image(systemName: icon)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 34, height: 34)
                    .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                Text(ReciLocalization.string(title))
                    .font(.body.weight(.medium))
                    .foregroundStyle(ReciTheme.ink)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(ReciTheme.muted.opacity(0.55))
            }
            .padding(.horizontal, 12)
            .frame(height: 56)
        }
        .buttonStyle(.plain)
    }
}

private struct SettingsSectionHeader: View {
    let icon: String
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
                .frame(width: 34, height: 34)
                .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(ReciLocalization.string(title))
                    .font(.headline.weight(.bold))
                    .foregroundStyle(ReciTheme.ink)
                Text(ReciLocalization.string(subtitle))
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.bottom, 4)
    }
}

private struct SettingsSegmentedRow<Option: Hashable>: View {
    let icon: String
    let title: String
    let subtitle: String
    let options: [Option]
    @Binding var selection: Option
    let label: (Option) -> String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(ReciTheme.muted)
                    .frame(width: 28, height: 28)

                VStack(alignment: .leading, spacing: 2) {
                    Text(ReciLocalization.string(title))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.ink)
                    Text(ReciLocalization.string(subtitle))
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                }
            }

            Picker(ReciLocalization.string(title), selection: $selection) {
                ForEach(options, id: \.self) { option in
                    Text(label(option)).tag(option)
                }
            }
            .pickerStyle(.segmented)
            .tint(ReciTheme.orange)
        }
        .padding(.vertical, 5)
    }
}

private struct SettingsMenuRow<Option: Hashable>: View {
    let icon: String
    let title: String
    let subtitle: String
    let options: [Option]
    @Binding var selection: Option
    let label: (Option) -> String

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(ReciTheme.muted)
                .frame(width: 28, height: 28)

            VStack(alignment: .leading, spacing: 2) {
                    Text(ReciLocalization.string(title))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.ink)
                    Text(ReciLocalization.string(subtitle))
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)
            }

            Spacer(minLength: 8)

            Picker(ReciLocalization.string(title), selection: $selection) {
                ForEach(options, id: \.self) { option in
                    Text(label(option)).tag(option)
                }
            }
            .pickerStyle(.menu)
            .tint(ReciTheme.ink)
        }
        .frame(minHeight: 54)
    }
}

private struct SettingsInfoRow: View {
    let icon: String
    let title: String
    let value: String

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(ReciTheme.muted)
                .frame(width: 28, height: 28)

            Text(ReciLocalization.string(title))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(ReciTheme.ink)

            Spacer(minLength: 8)

            Text(value)
                .font(.caption.weight(.medium))
                .foregroundStyle(ReciTheme.muted)
                .multilineTextAlignment(.trailing)
        }
        .frame(minHeight: 48)
    }
}

private struct HapticSettingsRow: View {
    @Binding var isEnabled: Bool

    private var hapticBinding: Binding<Bool> {
        Binding(
            get: { isEnabled },
            set: { newValue in
                guard newValue != isEnabled else { return }
                ReciHaptics.selection()
                isEnabled = newValue
            }
        )
    }

    var body: some View {
        Toggle(isOn: hapticBinding) {
            HStack(spacing: 13) {
                Image(systemName: "waveform")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(width: 34, height: 34)
                    .background(ReciTheme.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 13, style: .continuous))

                VStack(alignment: .leading, spacing: 2) {
                    Text(ReciLocalization.string("Haptics"))
                        .font(.body.weight(.medium))
                        .foregroundStyle(ReciTheme.ink)
                    Text(ReciLocalization.string("Tactile feedback for important actions"))
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                }
            }
        }
        .tint(ReciTheme.orange)
        .padding(.horizontal, 12)
        .frame(minHeight: 66)
    }
}
