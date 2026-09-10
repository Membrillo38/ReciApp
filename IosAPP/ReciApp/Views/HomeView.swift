import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var accessibilityReduceMotion
    @State private var presentedSheet: HomeSheet?
    @State private var selectedFolder: RecipeCategoryFolder?
    @State private var foldersAppeared = false
    @State private var homeAppeared = false
    @State private var addButtonExpanded = false
    @AppStorage("reciapp.folderSort.v1") private var folderSortRawValue = FolderSort.created.rawValue
    @AppStorage("reciapp.folderColumns.v1") private var folderColumns = 2
    @AppStorage("reciapp.folderLayout.v1") private var folderLayoutRawValue = CollectionLayout.grid.rawValue
    @State private var errorToastOffset: CGFloat = 0
    @Namespace private var folderAnimation

    private var folderSort: FolderSort {
        FolderSort(rawValue: folderSortRawValue) ?? .created
    }

    private var folderLayout: CollectionLayout {
        CollectionLayout(rawValue: folderLayoutRawValue) ?? .grid
    }

    private var columns: [GridItem] {
        if dynamicTypeSize.isAccessibilitySize {
            return [GridItem(.flexible())]
        }
        return Array(repeating: GridItem(.flexible(), spacing: 14), count: folderColumns)
    }

    var body: some View {
        let groupedRecipes = app.groupedRecipesCache
        let folders = app.childFolders(of: nil)

        NavigationStack {
            ZStack {
                ReciTheme.canvas.ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture {
                        collapsePasteButton()
                    }

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 24) {
                        homeHeader(recipeCount: app.recipes.count)
                            .homeEntrance(appeared: homeAppeared, delay: 0, reduceMotion: accessibilityReduceMotion)
                        if app.isLoading && app.recipes.isEmpty && !app.isImporting {
                            HomeLoadingSkeletons()
                                .homeEntrance(appeared: homeAppeared, delay: 0.10, reduceMotion: accessibilityReduceMotion)
                        } else {
                            statusContent
                                .homeEntrance(appeared: homeAppeared, delay: 0.10, reduceMotion: accessibilityReduceMotion)
                        folderSection(
                            folders: orderedFolders(folders),
                            groupedRecipes: groupedRecipes
                        )
                                .homeEntrance(appeared: homeAppeared, delay: 0.20, reduceMotion: accessibilityReduceMotion)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 10)
                    .padding(.bottom, 24)
                }
                .refreshable { await refreshRecipes() }
                .safeAreaInset(edge: .bottom, alignment: .leading, spacing: 0) {
                    HStack {
                        if addButtonExpanded {
                            pasteToast
                                .transition(.asymmetric(
                                    insertion: .scale(scale: 0.94).combined(with: .opacity),
                                    removal: .scale(scale: 0.98).combined(with: .opacity)
                                ))
                        } else {
                            addRecipeButton
                                .transition(.asymmetric(
                                    insertion: .scale(scale: 0.98).combined(with: .opacity),
                                    removal: .scale(scale: 0.94).combined(with: .opacity)
                                ))
                        }
                        if !addButtonExpanded {
                            Spacer(minLength: 0)
                        }
                    }
                    .homeEntrance(
                        appeared: homeAppeared,
                        delay: 0.28,
                        reduceMotion: accessibilityReduceMotion
                    )
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(ReciTheme.canvas)
                }

                if app.errorMessage != nil {
                    VStack {
                        appErrorToast
                        Spacer()
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
            .animation(.easeOut(duration: 0.2), value: app.errorMessage)
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $app.selectedRecipe) { recipe in
                RecipeDetailView(recipe: recipe)
            }
            .navigationDestination(item: $app.selectedRecipeSummary) { summary in
                RecipeLoadingView(summary: summary)
            }
            .navigationDestination(item: $selectedFolder) { folder in
                CategoryRecipesView(categoryName: folder.name, colorHex: folder.colorHex)
            }
            .sheet(item: $presentedSheet) { sheet in
                switch sheet {
                case .settings:
                    ProfileView()
                case .importRecipe:
                    ImportView()
                        .presentationDetents([.height(390)])
                        .presentationDragIndicator(.visible)
                        .presentationCornerRadius(36)
                        .presentationBackground(ReciTheme.canvas)
                case .folder(let state):
                    FolderEditorView(
                        folder: state.folder,
                        initialParent: state.parent,
                        onSave: { name, colorHex, parent in
                            if let folder = state.folder {
                                return app.updateCategory(folder.name, name: name, colorHex: colorHex, parent: parent)
                            } else {
                                return app.addCategory(name, colorHex: colorHex, parent: parent)
                            }
                        },
                        onDelete: state.folder.map { folder in
                            { requestDeleteFolder(folder) }
                        }
                    )
                    .presentationDetents([.medium])
                    .presentationDragIndicator(.visible)
                case .deleteFolder(let name):
                    FolderDeletionView(folderName: name)
                        .presentationDetents([.medium, .large])
                        .presentationDragIndicator(.visible)
                        .presentationCornerRadius(32)
                }
            }
            .onAppear {
                guard !homeAppeared else { return }
                if accessibilityReduceMotion {
                    homeAppeared = true
                    foldersAppeared = true
                } else {
                    withAnimation(.easeOut(duration: 0.32)) {
                        homeAppeared = true
                    }
                    Task { @MainActor in
                        try? await Task.sleep(for: .milliseconds(80))
                        guard !Task.isCancelled else { return }
                        foldersAppeared = true
                    }
                }
            }
        }
    }

    private func homeHeader(recipeCount: Int) -> some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text("My recipes")
                    .font(.system(size: 31, weight: .bold, design: .rounded))
                    .foregroundStyle(ReciTheme.ink)
                Text(recipeCount == 1
                     ? ReciLocalization.string("1 recipe saved")
                     : String(format: ReciLocalization.string("%d recipes saved"), recipeCount))
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
            }

            Spacer(minLength: 0)

            Button {
                ReciHaptics.lightImpact()
                presentedSheet = .settings
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(ReciTheme.orange)
                    .frame(width: 52, height: 52)
                    .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Settings")
        }
        .padding(.top, 4)
    }

    @ViewBuilder
    private var statusContent: some View {
        if app.isLoading && app.recipes.isEmpty && !app.isImporting {
            HStack(spacing: 12) {
                ProgressView().tint(ReciTheme.orange)
                Text("Loading your kitchen…")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        }

        if app.isImporting {
            ImportProgressCard(
                progress: app.importProgress,
                status: app.statusMessage,
                position: app.importQueuePosition,
                total: app.importQueueTotal,
                waitingHosts: app.importQueueHosts
            )
        } else if app.canResumeImport {
            ResumeImportCard {
                Task { await app.resumeImport() }
            }
        } else if let recipe = app.lastImportedRecipe {
            Button {
                ReciHaptics.selection()
                app.markImportedRecipeSeen(recipe.id)
                app.selectedRecipe = recipe
            } label: {
                ImportedRecipeCard(recipe: recipe)
            }
            .buttonStyle(.plain)
        }
    }

    private func folderSection(
        folders: [RecipeCategoryFolder],
        groupedRecipes: [String: [RecipeSummary]]
    ) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(alignment: .center, spacing: 0) {
                HStack(spacing: 6) {
                    Text("Folders")
                        .font(.system(size: 23, weight: .bold, design: .rounded))
                        .foregroundStyle(ReciTheme.ink)
                    Menu {
                    Picker(
                        "Sort folders",
                        selection: Binding(
                            get: { folderSort },
                            set: {
                                folderSortRawValue = $0.rawValue
                                ReciHaptics.selection()
                            }
                        )
                    ) {
                            ForEach(FolderSort.allCases) { sort in
                                Text(sort.title).tag(sort)
                            }
                        }

                        Divider()

                        Picker("Folders per row", selection: Binding(
                            get: { folderColumns },
                            set: {
                                folderColumns = $0
                                ReciHaptics.selection()
                            }
                        )) {
                            Text("1 per row").tag(1)
                            Text("2 per row").tag(2)
                            Text("3 per row").tag(3)
                        }

                        Divider()

                        Picker("Folder layout", selection: Binding(
                            get: { folderLayout },
                            set: {
                                folderLayoutRawValue = $0.rawValue
                                ReciHaptics.selection()
                            }
                        )) {
                            ForEach(CollectionLayout.allCases) { layout in
                                Label(layout.title, systemImage: layout.icon).tag(layout)
                            }
                        }
                    } label: {
                        Image(systemName: "chevron.down")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(ReciTheme.muted)
                            .frame(width: 28, height: 28)
                            .background(ReciTheme.surface, in: Circle())
                    }
                    .accessibilityLabel("Folder sorting and layout")
                }
                Spacer()
                Button {
                    ReciHaptics.mediumImpact()
                    presentedSheet = .folder(FolderEditorState(folder: nil, parent: nil))
                } label: {
                    Label("New", systemImage: "plus")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.orange)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(ReciTheme.orangeSoft, in: Capsule())
                }
                .buttonStyle(.plain)
            }

            Group {
                if folderLayout == .grid {
                    LazyVGrid(columns: columns, spacing: 16) {
                        folderItems(folders: folders, groupedRecipes: groupedRecipes, list: false)
                    }
                } else {
                    LazyVStack(spacing: 10) {
                        folderItems(folders: folders, groupedRecipes: groupedRecipes, list: true)
                    }
                }
            }
            .animation(.spring(response: 0.38, dampingFraction: 0.82), value: folderColumns)
            .animation(.spring(response: 0.46, dampingFraction: 0.84), value: folderSort)
            .animation(.easeInOut(duration: 0.2), value: folderLayout)
        }
    }

    @ViewBuilder
    private func folderItems(
        folders: [RecipeCategoryFolder],
        groupedRecipes: [String: [RecipeSummary]],
        list: Bool
    ) -> some View {
        ForEach(Array(folders.enumerated()), id: \.element.id) { index, folder in
            Button {
                ReciHaptics.selection()
                selectedFolder = folder
            } label: {
                if list {
                    FolderListRow(folder: folder, path: app.folderPath(folder.name))
                } else {
                    FolderTile(
                        folder: folder,
                        recipes: Array((groupedRecipes[folder.name] ?? []).prefix(3)),
                        isThreeColumnLayout: folderColumns == 3
                    )
                    .matchedGeometryEffect(id: folder.id, in: folderAnimation)
                }
            }
            .buttonStyle(FolderButtonStyle())
            .contextMenu { folderActions(for: folder) }
            .accessibilityLabel(
                String(format: ReciLocalization.string("%@, %@ recipes"), AppViewModel.localizedCategoryName(folder.name), String(folder.count))
            )
            .offset(y: foldersAppeared || accessibilityReduceMotion ? 0 : 8)
            .opacity(foldersAppeared ? 1 : 0)
            .animation(
                accessibilityReduceMotion ? nil : .easeOut(duration: 0.28).delay(Double(index) * 0.045),
                value: foldersAppeared
            )
        }
    }

    @ViewBuilder
    private func folderActions(for folder: RecipeCategoryFolder) -> some View {
        Button {
            ReciHaptics.selection()
            selectedFolder = folder
        } label: {
            Label("Open", systemImage: "arrow.up.right")
        }
        if folder.name != AppViewModel.uncategorized {
            Button {
                ReciHaptics.lightImpact()
                presentedSheet = .folder(FolderEditorState(folder: folder, parent: app.parentCategory(of: folder.name)))
            } label: {
                Label("Edit folder", systemImage: "pencil")
            }
            Menu {
                Button("Top level") {
                    _ = app.moveCategory(folder.name, to: nil)
                }
                ForEach(app.allCategoryNames.filter {
                    $0 != AppViewModel.uncategorized && app.canMoveCategory(folder.name, to: $0)
                }, id: \.self) { destination in
                    Button(app.folderPath(destination)) {
                        _ = app.moveCategory(folder.name, to: destination)
                    }
                }
            } label: {
                Label("Move folder…", systemImage: "folder.badge.arrow.forward")
            }
            Button(role: .destructive) {
                requestDeleteFolder(folder)
            } label: {
                Label("Delete folder", systemImage: "trash")
            }
        }
    }

    private func orderedFolders(_ folders: [RecipeCategoryFolder]) -> [RecipeCategoryFolder] {
        switch folderSort {
        case .created:
            return folders
        case .name:
            return folders.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        case .recipeCount:
            return folders.sorted { lhs, rhs in
                if lhs.count == rhs.count { return false }
                return lhs.count > rhs.count
            }
        }
    }

    private func requestDeleteFolder(_ folder: RecipeCategoryFolder) {
        guard folder.name != AppViewModel.uncategorized else { return }

        if app.recipes(in: folder.name).isEmpty {
            ReciHaptics.warning()
            app.deleteCategory(folder.name)
            ReciHaptics.success()
        } else {
            ReciHaptics.warning()
            presentedSheet = .deleteFolder(folder.name)
        }
    }

    private var appErrorToast: some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .foregroundStyle(ReciTheme.orange)

            Text(app.errorMessage ?? ReciLocalization.string("We couldn't update your recipes. Please try again."))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(ReciTheme.ink)
                .multilineTextAlignment(.leading)
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
                        withAnimation(.easeOut(duration: 0.2)) {
                            app.dismissError()
                        }
                    } else {
                        withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) {
                            errorToastOffset = 0
                        }
                    }
                }
        )
        .transition(.move(edge: .top).combined(with: .opacity))
        .task(id: app.errorMessage) {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.2)) {
                app.dismissError()
            }
        }
    }

    private var addRecipeButton: some View {
        Button {
            ReciHaptics.lightImpact()
            withAnimation(.spring(response: 0.42, dampingFraction: 0.80)) {
                addButtonExpanded = true
            }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "plus")
                    .font(.system(size: 19, weight: .bold))
                Text("Add recipe")
                    .font(.headline)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 20)
            .frame(height: 56)
            .background(ReciTheme.orange, in: Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Import a recipe link")
    }

    private var pasteToast: some View {
        ZStack {
            Button {
                collapsePasteButton()
                Task { await app.pasteAndImport() }
            } label: {
                Text("Paste from clipboard")
                    .font(.headline)
                .foregroundStyle(.white)
                .padding(.horizontal, 20)
                .frame(height: 56)
                .frame(maxWidth: .infinity)
                .multilineTextAlignment(.center)
            }

            Button {
                collapsePasteButton()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 34, height: 34)
                    .background(.white.opacity(0.20), in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close paste options")
            .padding(.trailing, 11)
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .background(ReciTheme.orange, in: Capsule())
        .shadow(color: ReciTheme.orange.opacity(0.24), radius: 14, y: 7)
    }

    private func collapsePasteButton() {
        guard addButtonExpanded else { return }
        ReciHaptics.lightImpact()
        withAnimation(.spring(response: 0.42, dampingFraction: 0.80)) {
            addButtonExpanded = false
        }
    }

    private func refreshRecipes() async {
        ReciHaptics.lightImpact()
        await app.refreshAll()
        if app.errorMessage == nil {
            ReciHaptics.success()
        }
    }

}

enum CollectionLayout: String, CaseIterable, Identifiable {
    case grid
    case list

    var id: String { rawValue }
    var title: String { ReciLocalization.string(rawValue.capitalized) }
    var icon: String { self == .grid ? "square.grid.2x2" : "list.bullet" }
}

enum FolderSort: String, CaseIterable, Identifiable {
    case created
    case name
    case recipeCount

    var id: String { rawValue }

    var title: String {
        switch self {
        case .created: ReciLocalization.string("Recently added")
        case .name: ReciLocalization.string("A–Z")
        case .recipeCount: ReciLocalization.string("Most recipes")
        }
    }
}

private enum HomeSheet: Identifiable {
    case settings
    case importRecipe
    case folder(FolderEditorState)
    case deleteFolder(String)

    var id: String {
        switch self {
        case .settings: "settings"
        case .importRecipe: "import"
        case .folder(let state): "folder-\(state.id)"
        case .deleteFolder(let name): "delete-\(name)"
        }
    }
}

private struct HomeLoadingSkeletons: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(ReciTheme.line)
                .frame(width: 92, height: 24)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .fill(ReciTheme.line)
                        .aspectRatio(1.22, contentMode: .fit)
                        .overlay {
                            ProgressView()
                                .tint(ReciTheme.muted.opacity(0.45))
                        }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .redacted(reason: .placeholder)
    }
}

private struct FolderDeletionView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss
    let folderName: String

    private var recipes: [RecipeSummary] { app.recipes(in: folderName) }
    private var otherFolders: [String] {
        app.allCategoryNames.filter { $0 != folderName && $0 != AppViewModel.uncategorized }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(spacing: 14) {
                        Image(systemName: "folder.fill")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(ReciTheme.orange)
                            .frame(width: 52, height: 52)
                            .background(ReciTheme.orangeSoft, in: Circle())

                        VStack(alignment: .leading, spacing: 4) {
                            Text(String(format: ReciLocalization.string("Delete %@?"), folderName))
                                .font(.title3.weight(.bold))
                                .foregroundStyle(ReciTheme.ink)
                            Text(String(format: ReciLocalization.string("%@ recipes will be moved"), String(recipes.count)))
                                .font(.subheadline)
                                .foregroundStyle(ReciTheme.muted)
                        }
                    }

                    Text("Choose where your recipes should go.")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(ReciTheme.muted)

                    VStack(spacing: 0) {
                        deletionActionRow(
                            title: "Move all to Uncategorized",
                            subtitle: "Keep recipes without a folder",
                            icon: "tray"
                        ) {
                            finishMove(to: AppViewModel.uncategorized)
                        }

                        if !otherFolders.isEmpty {
                            Divider().padding(.leading, 54)
                            Menu {
                                ForEach(otherFolders, id: \.self) { folder in
                                    Button(folder) {
                                        finishMove(to: folder)
                                    }
                                }
                            } label: {
                                deletionActionLabel(
                                    title: "Move all to another folder",
                                    subtitle: "Choose an existing folder",
                                    icon: "folder"
                                )
                            }
                        }
                    }
                    .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))

                }
                .padding(20)
            }
            .background(ReciTheme.canvas.ignoresSafeArea())
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                }
            }
        }
    }

    private func deletionActionRow(
        title: String,
        subtitle: String,
        icon: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            deletionActionLabel(title: title, subtitle: subtitle, icon: icon)
        }
        .buttonStyle(.plain)
    }

    private func deletionActionLabel(title: String, subtitle: String, icon: String) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
                .frame(width: 34, height: 34)
                .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 11, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(ReciLocalization.string(title))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.ink)
                Text(ReciLocalization.string(subtitle))
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(ReciTheme.muted.opacity(0.65))
        }
        .padding(14)
    }

    private func finishMove(to destination: String) {
        ReciHaptics.lightImpact()
        app.moveRecipes(withIDs: Set(recipes.map(\.id)), to: destination)
        app.deleteCategory(folderName)
        ReciHaptics.success()
        dismiss()
    }
}

private struct FolderButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .brightness(configuration.isPressed ? -0.025 : 0)
            .animation(.easeOut(duration: 0.16), value: configuration.isPressed)
    }
}

private struct FolderListRow: View {
    let folder: RecipeCategoryFolder
    let path: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "folder.fill")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(Color(hex: folder.colorHex))
                .frame(width: 48, height: 48)
                .background(Color(hex: folder.colorHex).opacity(0.16), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(AppViewModel.localizedCategoryName(folder.name))
                    .font(.headline)
                    .foregroundStyle(ReciTheme.ink)
                if path != folder.name {
                    Text(path)
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Text("\(folder.count)")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(ReciTheme.muted)
                .monospacedDigit()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(ReciTheme.muted.opacity(0.65))
        }
        .padding(13)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .contentShape(Rectangle())
    }
}

private extension View {
    func homeEntrance(appeared: Bool, delay: Double, reduceMotion: Bool) -> some View {
        opacity(appeared ? 1 : 0)
            .offset(y: appeared ? 0 : 10)
            .animation(
                reduceMotion ? nil : .easeOut(duration: 0.32).delay(delay),
                value: appeared
            )
    }
}

private struct FolderTile: View {
    let folder: RecipeCategoryFolder
    let recipes: [RecipeSummary]
    let isThreeColumnLayout: Bool

    var body: some View {
        FolderArtwork(folder: folder, recipes: recipes)
            .aspectRatio(isThreeColumnLayout ? 1.08 : 1.22, contentMode: .fit)
        .contentShape(Rectangle())
    }
}

private struct FolderArtwork: View {
    let folder: RecipeCategoryFolder
    let recipes: [RecipeSummary]

    private var color: Color { Color(hex: folder.colorHex) }

    private var textColor: Color {
        let clean = folder.colorHex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        guard let value = UInt64(clean, radix: 16) else { return ReciTheme.ink }
        let red = Double((value >> 16) & 0xFF) / 255
        let green = Double((value >> 8) & 0xFF) / 255
        let blue = Double(value & 0xFF) / 255
        let luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
        return luminance < 0.58 ? .white : ReciTheme.ink
    }

    private var previewRecipes: [RecipeSummary] {
        let withImages = recipes.filter { recipe in
            guard let thumbnailUrl = recipe.thumbnailUrl else { return false }
            return !thumbnailUrl.isEmpty
        }
        return Array((withImages.isEmpty ? recipes : withImages).prefix(2))
    }

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let height = proxy.size.height
            let tabHeight = height * 0.22
            let photoWidth = width - 20
            let photoHeight = height * 0.51
            let frontHeight = height * 0.64
            let compactText = width < 140

            ZStack(alignment: .topLeading) {
                FolderBackShape()
                    .fill(color.opacity(0.64))

                if previewRecipes.isEmpty {
                    Color.white.opacity(0.24)
                    .frame(width: photoWidth, height: photoHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .position(x: width / 2, y: tabHeight + 7 + photoHeight / 2)
                } else {
                    let overlap: CGFloat = 7
                    let imageWidth = previewRecipes.count == 1
                        ? photoWidth
                        : (photoWidth + overlap) / 2

                    HStack(spacing: -overlap) {
                        RecipeArtwork(
                            recipe: previewRecipes[0],
                            tint: color,
                            compact: true,
                            showsFallbackText: false
                        )
                        .frame(width: imageWidth, height: photoHeight)
                        .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))

                        if previewRecipes.count > 1 {
                            RecipeArtwork(
                                recipe: previewRecipes[1],
                                tint: color,
                                compact: true,
                                showsFallbackText: false
                            )
                            .frame(width: imageWidth, height: photoHeight)
                            .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
                            .offset(y: 2)
                        }
                    }
                    .frame(width: photoWidth, height: photoHeight, alignment: .leading)
                    .position(x: width / 2, y: tabHeight + 7 + photoHeight / 2)
                }

                ZStack {
                    RoundedRectangle(cornerRadius: 25, style: .continuous)
                        .fill(color)
                    RoundedRectangle(cornerRadius: 25, style: .continuous)
                        .fill(.white.opacity(0.07))
                }
                .frame(width: width, height: frontHeight)
                .position(x: width / 2, y: height - frontHeight / 2)

                VStack(alignment: .leading, spacing: 3) {
                    Text(AppViewModel.localizedCategoryName(folder.name))
                        .font(.system(
                            size: compactText ? 13 : min(17, max(13, width * 0.13)),
                            weight: .semibold,
                            design: .rounded
                        ))
                        .foregroundStyle(textColor.opacity(0.80))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .minimumScaleFactor(compactText ? 0.55 : 0.68)
                        .allowsTightening(true)
                        .lineSpacing(compactText ? 0 : -1)
                    Text(folder.count == 1
                         ? ReciLocalization.string("1 recipe")
                         : String(format: ReciLocalization.string("%d recipes"), folder.count))
                        .font(.system(
                            size: compactText ? 10.5 : min(12, max(10, width * 0.095)),
                            weight: .medium,
                            design: .rounded
                        ))
                        .foregroundStyle(textColor.opacity(0.80))
                        .monospacedDigit()
                }
                .frame(width: width - 28, height: frontHeight - 24, alignment: .bottomLeading)
                .position(x: width / 2, y: height - frontHeight / 2)

            }
            .frame(width: width, height: height)
        }
    }
}

private struct FolderBackShape: Shape {
    func path(in rect: CGRect) -> Path {
        let width = rect.width
        let height = rect.height
        let tabHeight = height * 0.22
        let tabWidth = width * 0.48
        let radius: CGFloat = 27

        var path = Path()
        path.move(to: CGPoint(x: 0, y: tabHeight))
        path.addLine(to: CGPoint(x: 0, y: 18))
        path.addQuadCurve(
            to: CGPoint(x: 18, y: 0),
            control: CGPoint(x: 0, y: 0)
        )
        path.addLine(to: CGPoint(x: tabWidth - 14, y: 0))
        path.addQuadCurve(
            to: CGPoint(x: tabWidth, y: 10),
            control: CGPoint(x: tabWidth - 4, y: 0)
        )
        path.addLine(to: CGPoint(x: tabWidth + 12, y: tabHeight))
        path.addLine(to: CGPoint(x: width - radius, y: tabHeight))
        path.addQuadCurve(
            to: CGPoint(x: width, y: tabHeight + radius),
            control: CGPoint(x: width, y: tabHeight)
        )
        path.addLine(to: CGPoint(x: width, y: height - radius))
        path.addQuadCurve(
            to: CGPoint(x: width - radius, y: height),
            control: CGPoint(x: width, y: height)
        )
        path.addLine(to: CGPoint(x: radius, y: height))
        path.addQuadCurve(
            to: CGPoint(x: 0, y: height - radius),
            control: CGPoint(x: 0, y: height)
        )
        path.closeSubpath()
        return path
    }
}

private struct RecipeArtwork: View {
    let recipe: RecipeSummary
    let tint: Color
    let compact: Bool
    let showsFallbackText: Bool

    var body: some View {
        AsyncImage(url: recipe.thumbnailUrl.flatMap(URL.init(string:))) { phase in
            if case .success(let image) = phase {
                image.resizable().scaledToFill()
            } else {
                ZStack(alignment: .bottomLeading) {
                    tint.opacity(compact ? 0.58 : 0.72)

                    Circle()
                        .fill(.white.opacity(0.14))
                        .frame(width: compact ? 52 : 150, height: compact ? 52 : 150)
                        .offset(x: compact ? 18 : 76, y: compact ? -20 : -74)

                    if showsFallbackText {
                        VStack(alignment: .leading, spacing: compact ? 3 : 7) {
                            Text(recipe.platform)
                                .font(.system(size: compact ? 7 : 10, weight: .bold))
                                .lineLimit(1)
                            Text(recipe.title)
                                .font(.system(size: compact ? 12 : 24, weight: .semibold, design: .rounded))
                                .lineLimit(compact ? 2 : 3)
                                .minimumScaleFactor(0.75)
                        }
                        .foregroundStyle(ReciTheme.ink.opacity(0.76))
                        .padding(compact ? 10 : 18)
                    }
                }
            }
        }
        .clipped()
    }
}

private struct FolderEditorState: Identifiable {
    let folder: RecipeCategoryFolder?
    let parent: String?
    var id: String { folder?.id ?? "new-\(parent ?? "root")" }
}

private struct FolderEditorView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss
    let folder: RecipeCategoryFolder?
    let initialParent: String?
    let onSave: (String, String, String?) -> Bool
    let onDelete: (() -> Void)?
    @State private var name: String
    @State private var color: Color
    @State private var parent: String?

    private let palette = ["0A84FF", "34C759", "FFC107", "FF5FA2", "FF7119", "A56BFF"]

    init(
        folder: RecipeCategoryFolder?,
        initialParent: String?,
        onSave: @escaping (String, String, String?) -> Bool,
        onDelete: (() -> Void)? = nil
    ) {
        self.folder = folder
        self.initialParent = initialParent
        self.onSave = onSave
        self.onDelete = onDelete
        _name = State(initialValue: folder?.name ?? "")
        _color = State(initialValue: Color(hex: folder?.colorHex ?? "F2C94C"))
        _parent = State(initialValue: initialParent)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 24) {
                TextField("Folder name", text: $name)
                    .font(.title3.weight(.semibold))
                    .padding(.horizontal, 16)
                    .frame(height: 54)
                    .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .onChange(of: name) {
                        if name.count > AppViewModel.categoryNameMaxLength {
                            name = String(name.prefix(AppViewModel.categoryNameMaxLength))
                        }
                    }

                Text("\(name.count)/\(AppViewModel.categoryNameMaxLength)")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
                    .frame(maxWidth: .infinity, alignment: .trailing)

                Menu {
                    Button("Top level") { parent = nil }
                    ForEach(parentDestinations, id: \.self) { destination in
                        Button(app.folderPath(destination)) { parent = destination }
                    }
                } label: {
                    HStack {
                        Label("Inside", systemImage: "folder")
                        Spacer()
                        Text(parent.map(app.folderPath) ?? ReciLocalization.string("Top level"))
                            .foregroundStyle(ReciTheme.muted)
                            .lineLimit(1)
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(ReciTheme.muted)
                    }
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.ink)
                    .padding(.horizontal, 16)
                    .frame(height: 52)
                    .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                }

                if let message = app.organizationErrorMessage {
                    Text(message)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 12) {
                    Text("Color")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.muted)

                    HStack(spacing: 13) {
                        ForEach(palette, id: \.self) { hex in
                            let swatch = Color(hex: hex)
                            Button {
                                ReciHaptics.selection()
                                color = swatch
                            } label: {
                                Circle()
                                    .fill(swatch)
                                    .frame(width: 38, height: 38)
                                    .overlay {
                                        Image(systemName: "checkmark")
                                            .font(.caption.weight(.bold))
                                            .foregroundStyle(.white)
                                            .opacity(color.hexString == hex ? 1 : 0)
                                    }
                            }
                            .buttonStyle(.plain)
                        }
                        ColorPicker("Custom color", selection: $color, supportsOpacity: false)
                            .labelsHidden()
                            .simultaneousGesture(
                                TapGesture().onEnded { ReciHaptics.lightImpact() }
                            )
                    }
                }

                if let onDelete {
                    Button(role: .destructive) {
                        onDelete()
                        dismiss()
                    } label: {
                        Label("Delete folder", systemImage: "trash")
                            .font(.subheadline.weight(.semibold))
                    }
                }

                Spacer()
            }
            .padding(20)
            .background(ReciTheme.canvas.ignoresSafeArea())
            .navigationTitle(ReciLocalization.string(folder == nil ? "New folder" : "Edit folder"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        if onSave(name, color.hexString, parent) {
                            ReciHaptics.success()
                            dismiss()
                        } else {
                            ReciHaptics.warning()
                        }
                    }
                    .fontWeight(.semibold)
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private var parentDestinations: [String] {
        app.allCategoryNames.filter { destination in
            guard destination != AppViewModel.uncategorized else { return false }
            guard let folder else { return true }
            return app.canMoveCategory(folder.name, to: destination)
        }
    }
}

private struct StatusBanner: View {
    let icon: String
    let title: String
    let message: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(tint)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.subheadline.weight(.semibold))
                Text(message)
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(ReciTheme.ink)
        .padding(15)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

private struct ImportProgressCard: View {
    let progress: Int
    let status: String
    var position: Int = 0
    var total: Int = 0
    var waitingHosts: [String] = []

    private var normalizedProgress: Double {
        Double(min(max(progress, 0), 100)) / 100
    }

    private var queueLabel: String? {
        guard total > 1, position > 0 else { return nil }
        return String(
            format: ReciLocalization.string("Recipe %d of %d"),
            position,
            total
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(queueLabel ?? ReciLocalization.string("Creating your recipe"))
                        .font(.headline)
                    Text(status.isEmpty ? ReciLocalization.string("Reading the link…") : status)
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                        .lineLimit(1)
                }
                Spacer()
                Text(normalizedProgress, format: .percent.precision(.fractionLength(0)))
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(ReciTheme.orange)
                    .monospacedDigit()
            }

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(ReciTheme.line)
                    Capsule()
                        .fill(ReciTheme.orange)
                        .frame(width: proxy.size.width * normalizedProgress)
                        .animation(.easeInOut(duration: 0.35), value: progress)
                }
            }
            .frame(height: 7)

            if waitingHosts.count > 1 {
                Text(waitingHosts.joined(separator: " · "))
                    .font(.caption2)
                    .foregroundStyle(ReciTheme.muted)
                    .lineLimit(2)
            }
        }
        .padding(17)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

private struct ResumeImportCard: View {
    let resume: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Import paused")
                .font(.headline)
                .foregroundStyle(ReciTheme.ink)
            Text("The server may still be working. Resume checks that job without starting a new import.")
                .font(.caption)
                .foregroundStyle(ReciTheme.muted)
                .fixedSize(horizontal: false, vertical: true)
            Button(action: resume) {
                Text("Resume import")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 44)
                    .background(ReciTheme.orange, in: Capsule())
            }
            .buttonStyle(.plain)
        }
        .padding(17)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

private struct ImportedRecipeCard: View {
    let recipe: RecipePublic

    var body: some View {
        HStack(spacing: 13) {
            AsyncImage(url: recipe.thumbnailUrl.flatMap(URL.init(string:))) { phase in
                if case .success(let image) = phase {
                    image.resizable().scaledToFill()
                } else {
                    ZStack {
                        ReciTheme.orangeSoft
                        Image(systemName: "fork.knife")
                            .foregroundStyle(ReciTheme.orange)
                    }
                }
            }
            .frame(width: 68, height: 68)
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                Text("Recipe ready")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(ReciTheme.green)
                    .textCase(.uppercase)
                Text(recipe.title)
                    .font(.headline)
                    .foregroundStyle(ReciTheme.ink)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(ReciTheme.muted)
        }
        .padding(10)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

private struct CategoryRecipesView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let categoryName: String
    let colorHex: String
    @State private var isSelecting = false
    @State private var selectedIDs: Set<UUID> = []
    @State private var tagEditor: TagEditorTarget?
    @State private var folderSheet: FolderScreenSheet?
    @AppStorage("reciapp.folderLayout.v1") private var folderLayoutRawValue = CollectionLayout.grid.rawValue
    @AppStorage("reciapp.recipeLayout.v1") private var recipeLayoutRawValue = CollectionLayout.grid.rawValue
    @AppStorage("reciapp.folderColumns.v1") private var folderColumns = 2

    private var recipes: [RecipeSummary] { app.recipes(in: categoryName) }
    private var childFolders: [RecipeCategoryFolder] { app.childFolders(of: categoryName) }
    private var recipeIDs: [UUID] { recipes.map(\.id) }
    private var moveDestinations: [String] {
        app.allCategoryNames.filter { $0 != categoryName }
    }
    private var canSelect: Bool { !recipes.isEmpty && !moveDestinations.isEmpty }
    private var folderLayout: CollectionLayout { CollectionLayout(rawValue: folderLayoutRawValue) ?? .grid }
    private var recipeLayout: CollectionLayout { CollectionLayout(rawValue: recipeLayoutRawValue) ?? .grid }
    private var columns: [GridItem] {
        if dynamicTypeSize.isAccessibilitySize {
            return [GridItem(.flexible())]
        }
        return [
            GridItem(.adaptive(minimum: 156, maximum: 220), spacing: 14),
        ]
    }
    private var subfolderColumns: [GridItem] {
        if dynamicTypeSize.isAccessibilitySize { return [GridItem(.flexible())] }
        return Array(repeating: GridItem(.flexible(), spacing: 14), count: folderColumns)
    }

    var body: some View {
        ZStack {
            ReciTheme.canvas.ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    categoryHeader

                    if !childFolders.isEmpty {
                        subfolderSection
                    }

                    if recipes.isEmpty && childFolders.isEmpty {
                        emptyState
                    } else if !recipes.isEmpty {
                        if recipeLayout == .grid {
                            LazyVGrid(columns: columns, spacing: 26) {
                                recipeItems(list: false)
                            }
                        } else {
                            LazyVStack(spacing: 10) {
                                recipeItems(list: true)
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 36)
            }
            .refreshable { await refreshRecipes() }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if isSelecting {
                    FolderSelectionBar(
                        canSelectAll: selectedIDs.count < recipes.count,
                        canMove: !selectedIDs.isEmpty,
                        destinations: moveDestinations,
                        onSelectAll: selectAll,
                        onMove: moveSelected(to:)
                    )
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(ReciTheme.canvas, for: .navigationBar)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if canSelect {
                    Button(ReciLocalization.string(isSelecting ? "Done" : "Select"), action: toggleSelecting)
                }
                if !isSelecting {
                    Menu {
                        Picker("Folder layout", selection: $folderLayoutRawValue) {
                            ForEach(CollectionLayout.allCases) { layout in
                                Label(layout.title, systemImage: layout.icon).tag(layout.rawValue)
                            }
                        }
                        Picker("Recipe layout", selection: $recipeLayoutRawValue) {
                            ForEach(CollectionLayout.allCases) { layout in
                                Label(layout.title, systemImage: layout.icon).tag(layout.rawValue)
                            }
                        }
                    } label: {
                        Image(systemName: "rectangle.grid.1x2")
                    }
                    .accessibilityLabel("Folder and recipe layout")

                    if categoryName != AppViewModel.uncategorized {
                        Button {
                            folderSheet = .editor(FolderEditorState(folder: nil, parent: categoryName))
                        } label: {
                            Image(systemName: "folder.badge.plus")
                        }
                        .accessibilityLabel("New subfolder")
                    }
                }
            }
        }
        .animation(.easeOut(duration: 0.2), value: isSelecting)
        .onChange(of: recipeIDs) { _, ids in
            selectedIDs.formIntersection(ids)
            if recipes.isEmpty { isSelecting = false }
        }
        .onChange(of: canSelect) { _, possible in
            if !possible {
                isSelecting = false
                selectedIDs = []
            }
        }
        .sheet(item: $tagEditor) { target in
            RecipeTagEditorView(recipeID: target.id)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationBackground(ReciTheme.canvas)
        }
        .sheet(item: $folderSheet) { sheet in
            switch sheet {
            case .editor(let state):
                FolderEditorView(
                    folder: state.folder,
                    initialParent: state.parent,
                    onSave: { name, color, parent in
                        if let folder = state.folder {
                            return app.updateCategory(folder.name, name: name, colorHex: color, parent: parent)
                        }
                        return app.addCategory(name, colorHex: color, parent: parent)
                    },
                    onDelete: state.folder.map { folder in { requestDeleteFolder(folder) } }
                )
                .presentationDetents([.medium, .large])
            case .delete(let name):
                FolderDeletionView(folderName: name)
                    .presentationDetents([.medium, .large])
            }
        }
    }

    @ViewBuilder
    private func recipeItems(list: Bool) -> some View {
                            ForEach(recipes) { recipe in
                                let isSelected = selectedIDs.contains(recipe.id)
                                ZStack(alignment: .topLeading) {
                                    Button {
                                        handleRecipeTap(recipe)
                                    } label: {
                                        if list {
                                            RecipeListRow(
                                                recipe: recipe,
                                                tint: Color(hex: colorHex),
                                                isSelecting: isSelecting,
                                                isSelected: isSelected,
                                                isFavorite: app.isFavorite(recipe.id),
                                                tags: app.tags(for: recipe.id)
                                            )
                                        } else {
                                            RecipeTile(
                                                recipe: recipe,
                                                tint: Color(hex: colorHex),
                                                isSelecting: isSelecting,
                                                isSelected: isSelected,
                                                isFavorite: app.isFavorite(recipe.id),
                                                tags: app.tags(for: recipe.id)
                                            )
                                        }
                                    }
                                    .buttonStyle(FolderButtonStyle())
                                    .accessibilityAddTraits(isSelecting && isSelected ? .isSelected : [])
                                    .contextMenu {
                                        recipeContextMenu(for: recipe)
                                    }
                                    .draggable(recipe.id.uuidString)

                                    if !isSelecting {
                                        Button {
                                            ReciHaptics.selection()
                                            app.toggleFavorite(recipe.id)
                                        } label: {
                                            Image(systemName: app.isFavorite(recipe.id) ? "heart.fill" : "heart")
                                                .font(.system(size: 16, weight: .semibold))
                                                .foregroundStyle(app.isFavorite(recipe.id) ? ReciTheme.orange : .white)
                                                .shadow(color: .black.opacity(0.35), radius: 4, y: 1)
                                                .frame(width: 44, height: 44)
                                                .contentShape(Rectangle())
                                        }
                                        .buttonStyle(.plain)
                                        .accessibilityLabel(
                                            ReciLocalization.string(
                                                app.isFavorite(recipe.id) ? "Remove favorite" : "Favorite"
                                            )
                                        )
                                    }
                                }
                            }
    }

    private var subfolderSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Subfolders")
                .font(.headline)
                .foregroundStyle(ReciTheme.ink)
            if folderLayout == .grid {
                LazyVGrid(columns: subfolderColumns, spacing: 14) { subfolderItems(list: false) }
            } else {
                LazyVStack(spacing: 10) { subfolderItems(list: true) }
            }
        }
    }

    @ViewBuilder
    private func subfolderItems(list: Bool) -> some View {
        ForEach(childFolders) { folder in
            RecipeFolderDropTarget(destination: folder.name, tint: Color(hex: folder.colorHex)) {
                NavigationLink {
                    CategoryRecipesView(categoryName: folder.name, colorHex: folder.colorHex)
                } label: {
                    if list {
                        FolderListRow(folder: folder, path: app.folderPath(folder.name))
                    } else {
                        FolderTile(
                            folder: folder,
                            recipes: Array(app.recipes(in: folder.name).prefix(3)),
                            isThreeColumnLayout: folderColumns == 3
                        )
                    }
                }
                .buttonStyle(FolderButtonStyle())
            }
            .contextMenu { subfolderActions(folder) }
        }
    }

    private var categoryHeader: some View {
        VStack(alignment: .leading, spacing: 8) {
            RoundedRectangle(cornerRadius: 5, style: .continuous)
                .fill(Color(hex: colorHex))
                .frame(width: 36, height: 10)
            Text(AppViewModel.localizedCategoryName(categoryName))
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if categoryName != AppViewModel.uncategorized {
                Text(app.folderPath(categoryName))
                    .font(.caption.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
                    .lineLimit(2)
            }
            Text(recipes.count == 1
                 ? ReciLocalization.string("1 saved recipe")
                 : String(format: ReciLocalization.string("%d saved recipes"), recipes.count))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(ReciTheme.muted)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 15) {
            EmptyFolderMark(tint: Color(hex: colorHex))
                .frame(width: 154, height: 138)

            Text(ReciLocalization.string(categoryName == AppViewModel.uncategorized ? "No folder assigned" : "This folder is empty"))
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
            Text(ReciLocalization.string(
                categoryName == AppViewModel.uncategorized
                    ? "Recipes without a folder appear here automatically."
                    : "Move a recipe here or create a subfolder."
            ))
                .font(.subheadline)
                .foregroundStyle(ReciTheme.muted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 370, alignment: .center)
        .padding(.horizontal, 24)
    }

    private func refreshRecipes() async {
        ReciHaptics.lightImpact()
        await app.refreshAll()
        if app.errorMessage == nil {
            ReciHaptics.success()
        }
    }

    @ViewBuilder
    private func subfolderActions(_ folder: RecipeCategoryFolder) -> some View {
        Button {
            folderSheet = .editor(FolderEditorState(folder: folder, parent: app.parentCategory(of: folder.name)))
        } label: {
            Label("Edit folder", systemImage: "pencil")
        }
        Menu {
            Button("Top level") { _ = app.moveCategory(folder.name, to: nil) }
            ForEach(app.allCategoryNames.filter {
                $0 != AppViewModel.uncategorized && app.canMoveCategory(folder.name, to: $0)
            }, id: \.self) { destination in
                Button(app.folderPath(destination)) { _ = app.moveCategory(folder.name, to: destination) }
            }
        } label: {
            Label("Move folder…", systemImage: "folder.badge.arrow.forward")
        }
        Button(role: .destructive) { requestDeleteFolder(folder) } label: {
            Label("Delete folder", systemImage: "trash")
        }
    }

    private func requestDeleteFolder(_ folder: RecipeCategoryFolder) {
        if app.recipes(in: folder.name).isEmpty {
            app.deleteCategory(folder.name)
            ReciHaptics.success()
        } else {
            ReciHaptics.warning()
            folderSheet = .delete(folder.name)
        }
    }

    @ViewBuilder
    private func recipeContextMenu(for recipe: RecipeSummary) -> some View {
        if !isSelecting {
            Button {
                ReciHaptics.selection()
                app.toggleFavorite(recipe.id)
            } label: {
                Label(
                    ReciLocalization.string(app.isFavorite(recipe.id) ? "Remove favorite" : "Favorite"),
                    systemImage: app.isFavorite(recipe.id) ? "heart.fill" : "heart"
                )
            }
            Button {
                ReciHaptics.selection()
                tagEditor = TagEditorTarget(id: recipe.id)
            } label: {
                Label(ReciLocalization.string("Tags"), systemImage: "tag")
            }
        }

        if !isSelecting, canSelect {
            Button(action: { beginSelecting(with: recipe.id) }) {
                Label(ReciLocalization.string("Select"), systemImage: "checkmark.circle")
            }
        }

        if !isSelecting, !moveDestinations.isEmpty {
            Menu {
                ForEach(moveDestinations, id: \.self) { destination in
                    Button {
                        ReciHaptics.selection()
                        app.setCategory(destination, for: recipe.id)
                    } label: {
                        Label(destination, systemImage: "folder")
                    }
                }
            } label: {
                Label("Move to…", systemImage: "folder")
            }
        }

        if !isSelecting {
            Button(role: .destructive) {
                ReciHaptics.warning()
                Task { await app.deleteRecipe(recipe) }
            } label: {
                Label("Delete recipe", systemImage: "trash")
            }
        }
    }

    private func handleRecipeTap(_ recipe: RecipeSummary) {
        ReciHaptics.selection()
        if isSelecting {
            toggleSelection(recipe.id)
        } else {
            app.selectedRecipeSummary = recipe
        }
    }

    private func toggleSelecting() {
        if isSelecting {
            endSelecting()
        } else {
            beginSelecting()
        }
    }

    private func beginSelecting(with id: UUID? = nil) {
        ReciHaptics.selection()
        isSelecting = true
        selectedIDs = id.map { [$0] } ?? []
    }

    private func endSelecting() {
        ReciHaptics.lightImpact()
        isSelecting = false
        selectedIDs = []
    }

    private func toggleSelection(_ id: UUID) {
        if selectedIDs.contains(id) {
            selectedIDs.remove(id)
        } else {
            selectedIDs.insert(id)
        }
        ReciHaptics.selection()
    }

    private func selectAll() {
        ReciHaptics.selection()
        selectedIDs = Set(recipeIDs)
    }

    private func moveSelected(to destination: String) {
        ReciHaptics.selection()
        app.moveRecipes(withIDs: selectedIDs, to: destination)
        isSelecting = false
        selectedIDs = []
    }
}

private enum FolderScreenSheet: Identifiable {
    case editor(FolderEditorState)
    case delete(String)

    var id: String {
        switch self {
        case .editor(let state): "editor-\(state.id)"
        case .delete(let name): "delete-\(name)"
        }
    }
}

private struct RecipeFolderDropTarget<Content: View>: View {
    @EnvironmentObject private var app: AppViewModel
    let destination: String
    let tint: Color
    @ViewBuilder let content: () -> Content
    @State private var isTargeted = false

    var body: some View {
        content()
            .padding(isTargeted ? 6 : 0)
            .background(
                isTargeted ? tint.opacity(0.18) : .clear,
                in: RoundedRectangle(cornerRadius: 24, style: .continuous)
            )
            .scaleEffect(isTargeted ? 1.02 : 1)
            .animation(.easeOut(duration: 0.16), value: isTargeted)
            .dropDestination(for: String.self) { items, _ in
                guard let raw = items.first,
                      let id = UUID(uuidString: raw),
                      app.recipes.contains(where: { $0.id == id }),
                      app.category(for: id) != destination else { return false }
                app.setCategory(destination, for: id)
                ReciHaptics.success()
                return true
            } isTargeted: { isTargeted = $0 }
            .accessibilityHint("Drop a recipe here to move it")
    }
}

private struct RecipeListRow: View {
    let recipe: RecipeSummary
    let tint: Color
    var isSelecting = false
    var isSelected = false
    var isFavorite = false
    var tags: [String] = []

    var body: some View {
        HStack(spacing: 13) {
            RecipeArtwork(recipe: recipe, tint: tint, compact: true, showsFallbackText: false)
                .frame(width: 68, height: 68)
                .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
                .overlay(alignment: .topTrailing) {
                    if isSelecting {
                        Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                            .symbolRenderingMode(.palette)
                            .foregroundStyle(.white, isSelected ? ReciTheme.green : .white.opacity(0.5))
                            .padding(5)
                    }
                }
            VStack(alignment: .leading, spacing: 5) {
                Text(recipe.title)
                    .font(.headline)
                    .foregroundStyle(ReciTheme.ink)
                    .lineLimit(2)
                HStack(spacing: 6) {
                    Text(recipe.platform)
                    if isFavorite { Image(systemName: "heart.fill").foregroundStyle(ReciTheme.orange) }
                    if !tags.isEmpty { Text(tags.prefix(2).joined(separator: " · ")) }
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(ReciTheme.muted)
                .lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(ReciTheme.muted.opacity(0.65))
        }
        .padding(10)
        .background(
            isSelecting && isSelected ? ReciTheme.orangeSoft : ReciTheme.surface,
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .contentShape(Rectangle())
        .opacity(isSelecting && !isSelected ? 0.72 : 1)
    }
}

private struct FolderSelectionBar: View {
    let canSelectAll: Bool
    let canMove: Bool
    let destinations: [String]
    let onSelectAll: () -> Void
    let onMove: (String) -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(ReciLocalization.string("Select All"), action: onSelectAll)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(canSelectAll ? ReciTheme.ink : ReciTheme.muted)
                .disabled(!canSelectAll)

            Spacer(minLength: 8)

            Menu {
                ForEach(destinations, id: \.self) { destination in
                    Button {
                        onMove(destination)
                    } label: {
                        Label(destination, systemImage: "folder")
                    }
                }
            } label: {
                Label(ReciLocalization.string("Move to…"), systemImage: "folder")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(canMove ? ReciTheme.ink : ReciTheme.muted)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(ReciTheme.surface, in: Capsule())
            }
            .disabled(!canMove)
            .accessibilityLabel(ReciLocalization.string("Move to…"))
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(ReciTheme.canvas)
    }
}

private struct TagEditorTarget: Identifiable {
    let id: UUID
}

struct RecipeCoverTags: View {
    let tags: [String]

    var body: some View {
        let visible = Array(tags.prefix(2))
        HStack(spacing: 4) {
            ForEach(visible, id: \.self) { tag in
                Text(tag)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(.black.opacity(0.45), in: Capsule())
            }
            if tags.count > visible.count {
                Text("+\(tags.count - visible.count)")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(.black.opacity(0.45), in: Capsule())
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(tags.joined(separator: ", "))
    }
}

struct RecipeTagEditorView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss
    let recipeID: UUID
    @State private var draft = ""

    private var tags: [String] { app.tags(for: recipeID) }
    private var canAdd: Bool {
        RecipeAnnotationPolicy.cleanedTag(draft) != nil && tags.count < RecipeAnnotationPolicy.tagMaxCount
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 8) {
                    TextField(ReciLocalization.string("Tag name"), text: $draft)
                        .textInputAutocapitalization(.words)
                        .submitLabel(.done)
                        .onSubmit(addTag)
                        .padding(.horizontal, 16)
                        .frame(height: 48)
                        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    Button(action: addTag) {
                        Text(ReciLocalization.string("Add tag"))
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 14)
                            .frame(height: 48)
                            .background(canAdd ? ReciTheme.orange : ReciTheme.line, in: Capsule())
                            .foregroundStyle(canAdd ? .white : ReciTheme.muted)
                    }
                    .disabled(!canAdd)
                }

                if tags.isEmpty {
                    Text(ReciLocalization.string("Tags"))
                        .font(.subheadline)
                        .foregroundStyle(ReciTheme.muted)
                } else {
                    ForEach(tags, id: \.self) { tag in
                        HStack {
                            Text(tag)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(ReciTheme.ink)
                            Spacer()
                            Button {
                                ReciHaptics.selection()
                                app.removeTag(tag, from: recipeID)
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(ReciTheme.muted)
                            }
                            .accessibilityLabel(ReciLocalization.string("Delete"))
                        }
                        .padding(.horizontal, 14)
                        .frame(height: 48)
                        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                }
                Spacer()
            }
            .padding(20)
            .background(ReciTheme.canvas.ignoresSafeArea())
            .navigationTitle(ReciLocalization.string("Tags"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(ReciLocalization.string("Done")) {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                }
            }
        }
    }

    private func addTag() {
        guard canAdd else { return }
        ReciHaptics.selection()
        app.addTag(draft, to: recipeID)
        draft = ""
    }
}

private struct EmptyFolderMark: View {
    let tint: Color

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let height = proxy.size.height

            ZStack(alignment: .bottom) {
                FolderBackShape()
                    .fill(tint.opacity(0.62))

                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(tint)
                    .frame(height: height * 0.58)

                Image(systemName: "plus")
                    .font(.system(size: 21, weight: .bold, design: .rounded))
                    .foregroundStyle(ReciTheme.ink.opacity(0.52))
                    .frame(width: 46, height: 46)
                    .background(.white.opacity(0.30), in: Circle())
                    .padding(.bottom, 18)
                    .accessibilityHidden(true)
            }
            .frame(width: width, height: height)
        }
        .accessibilityHidden(true)
    }
}

private struct RecipeTile: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let recipe: RecipeSummary
    let tint: Color
    var isSelecting = false
    var isSelected = false
    var isFavorite = false
    var tags: [String] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            GeometryReader { proxy in
                RecipeArtwork(
                    recipe: recipe,
                    tint: tint,
                    compact: false,
                    showsFallbackText: false
                )
                    .frame(width: proxy.size.width, height: proxy.size.height)
                    .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(alignment: .topTrailing) {
                        if isSelecting {
                            Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                                .font(.system(size: 22, weight: .semibold))
                                .symbolRenderingMode(.palette)
                                .foregroundStyle(
                                    isSelected ? Color.white : Color.white.opacity(0.95),
                                    isSelected ? ReciTheme.green : Color.white.opacity(0.45)
                                )
                                .padding(10)
                                .accessibilityHidden(true)
                        }
                    }
                    .overlay(alignment: .topLeading) {
                        if isSelecting, isFavorite {
                            Image(systemName: "heart.fill")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(ReciTheme.orange)
                                .padding(12)
                                .accessibilityHidden(true)
                        }
                    }
                    .overlay(alignment: .bottomLeading) {
                        if !tags.isEmpty {
                            RecipeCoverTags(tags: tags)
                                .padding(8)
                        }
                    }
            }
            .aspectRatio(dynamicTypeSize.isAccessibilitySize ? 1.35 : 0.8, contentMode: .fit)

            Text(recipe.title)
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
                .frame(minHeight: 44, alignment: .topLeading)

            HStack(spacing: 7) {
                Circle()
                    .fill(tint)
                    .frame(width: 6, height: 6)
                Text(recipe.platform)
                if let minutes = totalMinutes {
                    Text("·")
                    Text(String(format: ReciLocalization.string("%d min"), minutes))
                }
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(ReciTheme.muted)
            .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .opacity(isSelecting && !isSelected ? 0.72 : 1)
    }

    private var totalMinutes: Int? {
        let total = (recipe.prepMinutes ?? 0) + (recipe.cookMinutes ?? 0)
        return total > 0 ? total : nil
    }
}

#Preview("Folder home", traits: .fixedLayout(width: 390, height: 844)) {
    let app = AppViewModel()
    let recipes = [
        RecipeSummary(
            id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000001")!,
            title: "Creamy tomato pasta",
            platform: "Instagram",
            sourceUrl: "https://example.com/one",
            thumbnailUrl: nil,
            author: nil,
            servings: 2,
            prepMinutes: 10,
            cookMinutes: 20,
            savedAt: ""
        ),
        RecipeSummary(
            id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000002")!,
            title: "Crispy chicken bowl",
            platform: "TikTok",
            sourceUrl: "https://example.com/two",
            thumbnailUrl: nil,
            author: nil,
            servings: 4,
            prepMinutes: 15,
            cookMinutes: 25,
            savedAt: ""
        ),
        RecipeSummary(
            id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000003")!,
            title: "Roasted vegetables",
            platform: "YouTube",
            sourceUrl: "https://example.com/three",
            thumbnailUrl: nil,
            author: nil,
            servings: 3,
            prepMinutes: 8,
            cookMinutes: 30,
            savedAt: ""
        ),
    ]
    let configuredApp: AppViewModel = {
        app.recipes = recipes
        app.recipeCategories = [
            recipes[0].id: "Weeknight",
            recipes[1].id: "Weeknight",
            recipes[2].id: AppViewModel.uncategorized,
        ]
        app.customCategories = ["Weeknight"]
        app.categoryColors = ["Weeknight": "F2C94C"]
        return app
    }()

    HomeView()
        .environmentObject(configuredApp)
}
