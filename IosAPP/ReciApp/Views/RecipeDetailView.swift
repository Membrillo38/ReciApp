import Foundation
import SwiftUI

struct RecipeLoadingView: View {
    @EnvironmentObject private var app: AppViewModel
    @EnvironmentObject private var auth: AuthService
    let summary: RecipeSummary
    @State private var loadedRecipe: RecipePublic?
    @State private var loadError: String?
    @State private var retryID = 0

    var body: some View {
        Group {
            if let loadedRecipe {
                RecipeDetailView(recipe: loadedRecipe)
            } else if let loadError {
                RecipeLoadErrorView(message: loadError) {
                    retryID += 1
                }
            } else {
                RecipeDetailSkeletonView()
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .task(id: "\(summary.id.uuidString)-\(retryID)-\(auth.hasRestoredSession)") {
            guard auth.hasRestoredSession else { return }
            await loadRecipeWithRetry()
        }
        .onChange(of: app.selectedRecipe) { _, refreshed in
            guard refreshed?.id == summary.id else { return }
            loadedRecipe = refreshed
        }
        .onChange(of: app.refreshedDetail) { _, refreshed in
            guard refreshed?.id == summary.id else { return }
            loadedRecipe = refreshed
        }
    }

    private func loadRecipeWithRetry() async {
        loadedRecipe = nil
        loadError = nil

        do {
            loadedRecipe = try await app.fetchRecipe(summary)
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            loadError = error.localizedDescription
        }
    }
}

private struct RecipeDetailSkeletonView: View {
    var body: some View {
        ZStack {
            ReciTheme.canvas.ignoresSafeArea()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    RecipeSkeletonBlock(height: 360, cornerRadius: 0)

                    VStack(alignment: .leading, spacing: 28) {
                        VStack(alignment: .leading, spacing: 10) {
                            RecipeSkeletonBlock(width: 82, height: 13)
                            RecipeSkeletonBlock(width: 270, height: 38, cornerRadius: 10)
                            RecipeSkeletonBlock(width: 130, height: 15)
                        }

                        HStack(spacing: 10) {
                            ForEach(0..<3, id: \.self) { _ in
                                VStack(alignment: .leading, spacing: 8) {
                                    RecipeSkeletonBlock(width: 18, height: 18, cornerRadius: 6)
                                    RecipeSkeletonBlock(width: 42, height: 20, cornerRadius: 7)
                                    RecipeSkeletonBlock(width: 56, height: 12, cornerRadius: 6)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .padding(16)
                        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))

                        HStack(spacing: 12) {
                            RecipeSkeletonBlock(height: 72, cornerRadius: 22)
                            RecipeSkeletonBlock(height: 72, cornerRadius: 22)
                        }

                        skeletonTextBlock(lineCount: 3)
                        skeletonSection(rowCount: 5)
                        skeletonSection(rowCount: 3)
                        RecipeSkeletonBlock(height: 58, cornerRadius: 29)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 22)
                    .padding(.bottom, 38)
                }
            }
            .ignoresSafeArea(edges: .top)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Loading recipe")
    }

    private func skeletonTextBlock(lineCount: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(0..<lineCount, id: \.self) { index in
                RecipeSkeletonBlock(
                    width: index == lineCount - 1 ? 190 : nil,
                    height: 16,
                    cornerRadius: 8
                )
            }
        }
    }

    private func skeletonSection(rowCount: Int) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                RecipeSkeletonBlock(width: 128, height: 26, cornerRadius: 9)
                RecipeSkeletonBlock(width: 20, height: 16, cornerRadius: 7)
            }

            VStack(spacing: 14) {
                ForEach(0..<rowCount, id: \.self) { _ in
                    HStack(spacing: 12) {
                        RecipeSkeletonBlock(width: 8, height: 8, cornerRadius: 4)
                        RecipeSkeletonBlock(width: 62, height: 16, cornerRadius: 8)
                        RecipeSkeletonBlock(height: 16, cornerRadius: 8)
                    }
                }
            }
            .padding(16)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }
}

private struct RecipeSkeletonBlock: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isDimmed = false
    let width: CGFloat?
    let height: CGFloat
    var cornerRadius: CGFloat = 12

    init(width: CGFloat? = nil, height: CGFloat, cornerRadius: CGFloat = 12) {
        self.width = width
        self.height = height
        self.cornerRadius = cornerRadius
    }

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(ReciTheme.line.opacity(isDimmed ? 0.58 : 1))
            .frame(maxWidth: width == nil ? .infinity : nil)
            .frame(width: width, height: height)
            .animation(
                reduceMotion ? nil : .easeInOut(duration: 0.85).repeatForever(autoreverses: true),
                value: isDimmed
            )
            .onAppear {
                guard !reduceMotion else { return }
                isDimmed = true
            }
    }
}

private struct RecipeLoadErrorView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 27, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
                .frame(width: 64, height: 64)
                .background(ReciTheme.orangeSoft, in: Circle())

            Text("Couldn't load recipe")
                .font(.title3.weight(.bold))
                .foregroundStyle(ReciTheme.ink)

            Text(message)
                .font(.subheadline)
                .foregroundStyle(ReciTheme.muted)
                .multilineTextAlignment(.center)

            Button("Try again", action: retry)
                .font(.headline)
                .foregroundStyle(.white)
                .padding(.horizontal, 22)
                .frame(height: 52)
                .background(ReciTheme.orange, in: Capsule())
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ReciTheme.canvas.ignoresSafeArea())
    }
}

struct RecipeDetailView: View {
    @EnvironmentObject private var app: AppViewModel
    let recipe: RecipePublic
    @State private var showNewCategory = false
    @State private var showIngredientEditor = false
    @State private var showCooking = false
    @State private var showTagEditor = false
    @State private var newCategoryName = ""
    @State private var adjustedIngredientSections: [IngredientSection]?
    @State private var isDescriptionExpanded = false

    private var folderTint: Color {
        Color(hex: app.colorHex(for: app.category(for: recipe.id)))
    }

    private var sourceIngredientSections: [IngredientSection] {
        IngredientSectionPolicy.displayed(flat: recipe.ingredients, sections: recipe.ingredientSections)
    }

    private var displayedIngredientSections: [IngredientSection] {
        if let adjustedIngredientSections {
            return adjustedIngredientSections.filter { !$0.ingredients.isEmpty }
        }
        return sourceIngredientSections
    }

    private var displayedIngredients: [Ingredient] {
        displayedIngredientSections.flatMap(\.ingredients)
    }

    private var shouldOfferDescriptionExpansion: Bool {
        guard let description = recipe.description else { return false }
        return description.count > 120
    }

    private var heroImageURLs: [URL] {
        var values = recipe.carouselImageUrls.compactMap(URL.init(string:))
        if values.isEmpty, let thumbnail = recipe.thumbnailUrl.flatMap(URL.init(string:)) {
            values = [thumbnail]
        }
        var seen = Set<URL>()
        return values.filter { seen.insert($0).inserted }
    }

    var body: some View {
        ZStack {
            ReciTheme.canvas.ignoresSafeArea()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    hero

                    VStack(alignment: .leading, spacing: 28) {
                        titleBlock
                        quickFacts
                        primaryActions

                        if recipe.description?.isEmpty == false {
                            descriptionSection
                        }

                        if !recipe.tags.isEmpty {
                            tags
                        }

                        if !displayedIngredients.isEmpty {
                            ingredientsSection
                        }

                        if !recipe.steps.isEmpty {
                            methodSection
                        }

                        if !recipe.tips.isEmpty {
                            tipsSection
                        }

                        if let url = URL(string: recipe.sourceUrl) {
                            sourceButton(url: url)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 22)
                    .padding(.bottom, 38)
                }
            }
            .ignoresSafeArea(edges: .top)
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .alert("New folder", isPresented: $showNewCategory) {
            TextField("Name", text: $newCategoryName)
            Button("Save") {
                ReciHaptics.success()
                app.setCategory(newCategoryName, for: recipe.id)
                newCategoryName = ""
            }
            Button("Cancel", role: .cancel) {
                ReciHaptics.lightImpact()
                newCategoryName = ""
            }
        } message: {
            Text("Create a folder and move this recipe into it.")
        }
        .sheet(isPresented: $showIngredientEditor) {
            IngredientAdjustmentView(sections: displayedIngredientSections) { sections in
                adjustedIngredientSections = sections
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
            .presentationCornerRadius(32)
            .presentationBackground(ReciTheme.canvas)
        }
        .sheet(isPresented: $showTagEditor) {
            RecipeTagEditorView(recipeID: recipe.id)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationBackground(ReciTheme.canvas)
        }
        .fullScreenCover(isPresented: $showCooking) {
            // Cooking mode owns its own action feedback.
            CookingView(recipe: recipe, ingredientSections: displayedIngredientSections, tint: folderTint)
        }
        .onAppear {
            app.markImportedRecipeSeen(recipe.id)
        }
    }

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            if heroImageURLs.isEmpty {
                ZStack(alignment: .bottomLeading) {
                    folderTint.opacity(0.7)
                    Text(String(recipe.title.prefix(1)).uppercased())
                        .font(.system(size: 152, weight: .bold, design: .rounded))
                        .foregroundStyle(ReciTheme.ink.opacity(0.08))
                        .offset(x: -8, y: 36)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 7) {
                        Text(recipe.platform)
                            .font(.caption.weight(.semibold))
                        Text(recipe.title)
                            .font(.system(size: 29, weight: .semibold, design: .rounded))
                            .lineLimit(3)
                    }
                    .foregroundStyle(ReciTheme.ink.opacity(0.78))
                    .padding(22)
                }
            } else {
                RecipeCarouselView(images: heroImageURLs, height: 360, fallback: folderTint.opacity(0.7))
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 360)
        .clipped()
        .overlay(alignment: .top) {
            LinearGradient(
                colors: [.black.opacity(0.28), .clear],
                startPoint: .top,
                endPoint: .bottom
            )
            .frame(height: 145)
            .allowsHitTesting(false)
        }
        .overlay(alignment: .topTrailing) {
            Button {
                ReciHaptics.selection()
                app.toggleFavorite(recipe.id)
            } label: {
                Image(systemName: app.isFavorite(recipe.id) ? "heart.fill" : "heart")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(app.isFavorite(recipe.id) ? ReciTheme.orange : .white)
                    .frame(width: 44, height: 44)
                    .background(.black.opacity(0.28), in: Circle())
            }
            .buttonStyle(.plain)
            .padding(.top, 56)
            .padding(.trailing, 16)
            .accessibilityLabel(
                ReciLocalization.string(app.isFavorite(recipe.id) ? "Remove favorite" : "Favorite")
            )
        }
        .overlay(alignment: .bottomLeading) {
            let userTags = app.tags(for: recipe.id)
            if !userTags.isEmpty {
                RecipeCoverTags(tags: userTags)
                    .padding(16)
            }
        }
    }

    private var titleBlock: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(recipe.platform)
                .font(.caption.weight(.semibold))
                .foregroundStyle(ReciTheme.muted)

            Text(recipe.title)
                .font(.system(size: 35, weight: .bold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
                .fixedSize(horizontal: false, vertical: true)

            if let author = recipe.author, !author.isEmpty {
                Text(String(format: ReciLocalization.string("By %@"), author))
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(ReciTheme.muted)
            }
        }
    }

    private var quickFacts: some View {
        HStack(alignment: .top, spacing: 10) {
            if let minutes = totalMinutes {
                QuickFact(icon: "clock", value: "\(minutes)", label: "minutes")
            }
            if let servings = recipe.servings {
                QuickFact(icon: "person.2", value: "\(servings)", label: "servings")
            }
            QuickFact(icon: "list.number", value: "\(recipe.steps.count)", label: "steps")
        }
        .padding(16)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private var primaryActions: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                folderMenu

                Button {
                    ReciHaptics.mediumImpact()
                    showCooking = true
                } label: {
                    HStack(alignment: .center, spacing: 10) {
                        Image(systemName: "play.fill")
                            .font(.system(size: 15, weight: .bold))

                        VStack(alignment: .leading, spacing: 2) {
                            Text("Cook")
                                .font(.subheadline.weight(.bold))
                            Text("Step by step")
                                .font(.caption.weight(.medium))
                                .opacity(0.82)
                        }
                    }
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                    .padding(.horizontal, 14)
                    .background(ReciTheme.orange, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(recipe.steps.isEmpty)
                .opacity(recipe.steps.isEmpty ? 0.45 : 1)
                .accessibilityLabel("Start cooking step by step")
            }

            Button {
                ReciHaptics.selection()
                showTagEditor = true
            } label: {
                HStack(spacing: 11) {
                    Image(systemName: "tag.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(folderTint)
                        .frame(width: 32, height: 32)
                        .background(folderTint.opacity(0.16), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(ReciLocalization.string("Tags"))
                            .font(.caption.weight(.medium))
                            .foregroundStyle(ReciTheme.muted)
                        Text(app.tags(for: recipe.id).isEmpty
                             ? ReciLocalization.string("Add tag")
                             : app.tags(for: recipe.id).joined(separator: ", "))
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(ReciTheme.ink)
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)
                    }
                    Spacer()
                }
                .padding(.horizontal, 13)
                .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(ReciLocalization.string("Tags"))
        }
    }

    private var folderMenu: some View {
        Menu {
            if app.category(for: recipe.id) == AppViewModel.uncategorized {
                Label("Uncategorized (default)", systemImage: "tray")
            }

            ForEach(app.allCategoryNames.filter { $0 != AppViewModel.uncategorized }, id: \.self) { category in
                Button {
                    ReciHaptics.selection()
                    app.setCategory(category, for: recipe.id)
                } label: {
                    if app.category(for: recipe.id) == category {
                        Label(AppViewModel.localizedCategoryName(category), systemImage: "checkmark")
                    } else {
                        Text(AppViewModel.localizedCategoryName(category))
                    }
                }
            }
            Divider()
            Button {
                ReciHaptics.mediumImpact()
                showNewCategory = true
            } label: {
                Label("New folder", systemImage: "plus")
            }
        } label: {
            HStack(spacing: 11) {
                Image(systemName: "folder.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(folderTint)
                    .frame(width: 32, height: 32)
                    .background(folderTint.opacity(0.16), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Saved in")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(ReciTheme.muted)
                    Text(AppViewModel.localizedCategoryName(app.category(for: recipe.id)))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                Spacer()
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(ReciTheme.muted)
            }
            .padding(.horizontal, 13)
            .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
        .frame(maxWidth: .infinity)
        .accessibilityLabel("Change recipe folder")
    }

    private var tags: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(recipe.tags, id: \.self) { tag in
                    Text(tag)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ReciTheme.ink.opacity(0.68))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(folderTint.opacity(0.16), in: Capsule())
                }
            }
        }
        .scrollClipDisabled()
    }

    private var descriptionSection: some View {
        Group {
            if let description = recipe.description, !description.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text(description)
                        .font(.system(size: 17))
                        .foregroundStyle(ReciTheme.ink.opacity(0.68))
                        .lineSpacing(5)
                        .lineLimit(isDescriptionExpanded ? nil : 2)
                        .fixedSize(horizontal: false, vertical: true)

                    if shouldOfferDescriptionExpansion {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isDescriptionExpanded.toggle()
                            }
                            ReciHaptics.lightImpact()
                        } label: {
                            Text(isDescriptionExpanded ? "Less" : "More…")
                                .font(.subheadline.weight(.bold))
                                .foregroundStyle(ReciTheme.orange)
                        }
                        .buttonStyle(.plain)
                        .accessibilityHint("Expands or collapses the video description")
                    }
                }
            }
        }
    }

    private var ingredientsSection: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                RecipeSectionHeader(title: "Ingredients", count: displayedIngredients.count)
                Spacer(minLength: 0)
                Button {
                    ReciHaptics.lightImpact()
                    showIngredientEditor = true
                } label: {
                    Label("Adjust", systemImage: "sparkles")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(ReciTheme.orange)
                        .padding(.horizontal, 11)
                        .padding(.vertical, 8)
                        .background(ReciTheme.orangeSoft, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Adjust ingredients")
            }

            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(displayedIngredientSections.enumerated()), id: \.offset) { index, section in
                    IngredientSectionView(
                        section: section,
                        tint: folderTint,
                        showsTitle: displayedIngredientSections.count > 1 || index > 0 || section.title != "Ingredients"
                    )
                }
            }
        }
    }

    private var methodSection: some View {
        VStack(alignment: .leading, spacing: 20) {
            RecipeSectionHeader(title: "Method", count: recipe.steps.count)

            VStack(alignment: .leading, spacing: 0) {
                ForEach(recipe.steps.sorted(by: { $0.order < $1.order })) { step in
                    HStack(alignment: .top, spacing: 14) {
                        Text("\(step.order)")
                            .font(.headline.weight(.bold))
                            .foregroundStyle(ReciTheme.ink.opacity(0.68))
                            .frame(width: 36, height: 36)
                            .background(folderTint.opacity(0.22), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .frame(width: 40, alignment: .leading)

                        VStack(alignment: .leading, spacing: 9) {
                            Text(step.text)
                                .font(.body)
                                .foregroundStyle(ReciTheme.ink)
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                            if let minutes = step.durationMinutes {
                                Label(String(format: ReciLocalization.string("%d min"), minutes), systemImage: "clock")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(ReciTheme.muted)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 12)
                }
            }
        }
    }

    private var tipsSection: some View {
        VStack(alignment: .leading, spacing: 18) {
            RecipeSectionHeader(title: "Tips", count: recipe.tips.count)

            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(recipe.tips.enumerated()), id: \.offset) { _, tip in
                    RecipeTipRow(tip: tip, tint: folderTint)
                }
            }
            .padding(16)
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }

    private func sourceButton(url: URL) -> some View {
        Link(destination: url) {
            HStack {
                Label("View original recipe", systemImage: "safari")
                    .font(.headline)
                Spacer()
                Image(systemName: "arrow.up.right")
                    .font(.subheadline.weight(.semibold))
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .frame(minHeight: 58)
            .background(ReciTheme.ink, in: Capsule())
        }
        .simultaneousGesture(TapGesture().onEnded { ReciHaptics.lightImpact() })
    }

    private var totalMinutes: Int? {
        let total = (recipe.prepMinutes ?? 0) + (recipe.cookMinutes ?? 0)
        return total > 0 ? total : nil
    }

}

private struct QuickFact: View {
    let icon: String
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(ReciTheme.muted)
            Text(value)
                .font(.system(size: 19, weight: .semibold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
            Text(ReciLocalization.string(label))
                .font(.caption)
                .foregroundStyle(ReciTheme.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct RecipeSectionHeader: View {
    let title: String
    let count: Int

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(ReciLocalization.string(title))
                .font(.system(size: 24, weight: .bold, design: .rounded))
                .foregroundStyle(ReciTheme.ink)
            Text("\(count)")
                .font(.caption.weight(.semibold))
                .foregroundStyle(ReciTheme.muted)
        }
    }
}

private struct IngredientSectionView: View {
    let section: IngredientSection
    let tint: Color
    let showsTitle: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if showsTitle {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(section.title)
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(ReciTheme.ink)
                    Text("\(section.ingredients.count)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ReciTheme.muted)
                }
                .padding(.horizontal, 4)
            }

            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(section.ingredients.enumerated()), id: \.offset) { _, ingredient in
                    IngredientRow(ingredient: ingredient, tint: tint)
                }
            }
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }
}

private struct IngredientRow: View {
    let ingredient: Ingredient
    let tint: Color

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Circle()
                .fill(tint)
                .frame(width: 7, height: 7)
            Text(ingredient.quantity ?? "—")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(ReciTheme.ink)
                .monospacedDigit()
                .frame(width: 58, alignment: .trailing)
            Text(ingredient.unit ?? "")
                .font(.caption.weight(.semibold))
                .foregroundStyle(ReciTheme.muted)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .frame(width: 72, alignment: .leading)
            Text(ingredient.name)
                .font(.body)
                .foregroundStyle(ReciTheme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 15)
        .padding(.vertical, 13)
    }
}

private struct RecipeTipRow: View {
    let tip: RecipeTip
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lightbulb.fill")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(tint.opacity(0.14), in: Circle())

            VStack(alignment: .leading, spacing: 4) {
                if let title = tip.title, !title.isEmpty {
                    Text(title)
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(ReciTheme.ink)
                }
                Text(tip.text)
                    .font(.body)
                    .foregroundStyle(ReciTheme.ink.opacity(0.78))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct EditableIngredient: Identifiable {
    let id = UUID()
    let baseQuantity: Double?
    var name: String
    var quantity: String
    var unit: String

    init(_ ingredient: Ingredient) {
        baseQuantity = IngredientQuantityMath.parse(ingredient.quantity)
        name = ingredient.name
        quantity = ingredient.quantity ?? ""
        unit = ingredient.unit ?? ""
    }

    var ingredient: Ingredient {
        Ingredient(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            quantity: quantity.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty,
            unit: unit.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        )
    }
}

private enum IngredientQuantityMath {
    static func parse(_ rawValue: String?) -> Double? {
        guard let rawValue else { return nil }
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }

        let normalized = value.replacingOccurrences(of: ",", with: ".")
        if let decimal = Double(normalized) {
            return decimal
        }

        let fraction = normalized.split(separator: "/", omittingEmptySubsequences: true)
        guard fraction.count == 2,
              let numerator = Double(String(fraction[0]).trimmingCharacters(in: .whitespaces)),
              let denominator = Double(String(fraction[1]).trimmingCharacters(in: .whitespaces)),
              denominator != 0 else {
            return nil
        }
        return numerator / denominator
    }

    static func format(_ value: Double, unit: String?) -> String {
        let rounded: Double
        if isCountBased(unit: unit) {
            rounded = value > 0 ? max(1, value.rounded()) : 0
        } else {
            rounded = (value * 100).rounded() / 100
        }

        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: AppLanguageStore.current.localeIdentifier)
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = false
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: rounded)) ?? String(rounded)
    }

    private static func isCountBased(unit: String?) -> Bool {
        guard let unit else { return true }
        let normalized = unit
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard !normalized.isEmpty else { return true }

        return [
            "item", "items", "unit", "units", "ud", "uds", "unidad", "unidades",
            "piece", "pieces", "pieza", "piezas", "pc", "pcs", "each",
            "egg", "eggs", "huevo", "huevos", "clove", "cloves", "diente", "dientes",
            "can", "cans", "lata", "latas", "slice", "slices", "rodaja", "rodajas",
            "sprig", "sprigs", "ramita", "ramitas", "handful", "handfuls", "puñado", "puñados",
            "bunch", "bunches", "manojo", "manojos", "leaf", "leaves", "hoja", "hojas",
            "stalk", "stalks", "tallo", "tallos"
        ].contains(normalized)
    }
}

private struct EditableIngredientSection: Identifiable {
    let id = UUID()
    let title: String
    var drafts: [EditableIngredient]

    init(_ section: IngredientSection) {
        title = section.title
        drafts = section.ingredients.map(EditableIngredient.init)
    }

    var section: IngredientSection {
        IngredientSection(
            title: title,
            ingredients: drafts
                .map(\.ingredient)
                .filter { !$0.name.isEmpty }
        )
    }
}

private struct IngredientAdjustmentView: View {
    @Environment(\.dismiss) private var dismiss
    let onSave: ([IngredientSection]) -> Void
    @State private var draftSections: [EditableIngredientSection]

    init(sections: [IngredientSection], onSave: @escaping ([IngredientSection]) -> Void) {
        self.onSave = onSave
        _draftSections = State(initialValue: sections.map(EditableIngredientSection.init))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack(spacing: 12) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(ReciTheme.orange)
                            .frame(width: 42, height: 42)
                            .background(ReciTheme.orangeSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

                        VStack(alignment: .leading, spacing: 3) {
                            Text("Make it fit what you have")
                                .font(.headline)
                                .foregroundStyle(ReciTheme.ink)
                            Text("Change one amount and the rest scales automatically.")
                                .font(.caption)
                                .foregroundStyle(ReciTheme.muted)
                        }
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(draftSections.indices, id: \.self) { sectionIndex in
                            VStack(alignment: .leading, spacing: 8) {
                                if draftSections.count > 1 || draftSections[sectionIndex].title != "Ingredients" {
                                    Text(draftSections[sectionIndex].title)
                                        .font(.subheadline.weight(.bold))
                                        .foregroundStyle(ReciTheme.ink)
                                        .padding(.horizontal, 4)
                                }

                                VStack(spacing: 0) {
                                    ForEach(draftSections[sectionIndex].drafts.indices, id: \.self) { ingredientIndex in
                                        HStack(alignment: .center, spacing: 8) {
                                            TextField(
                                                "Qty",
                                                text: quantityBinding(
                                                    sectionIndex: sectionIndex,
                                                    ingredientIndex: ingredientIndex
                                                )
                                            )
                                            .font(.subheadline.weight(.semibold))
                                            .keyboardType(.decimalPad)
                                            .multilineTextAlignment(.trailing)
                                            .frame(width: 58)

                                            TextField("Unit", text: $draftSections[sectionIndex].drafts[ingredientIndex].unit)
                                                .font(.caption.weight(.semibold))
                                                .foregroundStyle(ReciTheme.muted)
                                                .lineLimit(1)
                                                .minimumScaleFactor(0.72)
                                                .frame(width: 72, alignment: .leading)

                                            TextField("Ingredient", text: $draftSections[sectionIndex].drafts[ingredientIndex].name)
                                                .font(.body)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                        }
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 13)

                                        if ingredientIndex < draftSections[sectionIndex].drafts.count - 1 {
                                            Divider()
                                                .padding(.leading, 14)
                                        }
                                    }
                                }
                                .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                            }
                        }
                    }

                    Button {
                        ReciHaptics.success()
                        onSave(draftSections.map(\.section).filter { !$0.ingredients.isEmpty })
                        dismiss()
                    } label: {
                        Label("Apply adjustments", systemImage: "checkmark")
                            .font(.headline)
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, minHeight: 56)
                            .background(ReciTheme.orange, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
                .padding(20)
            }
            .background(ReciTheme.canvas.ignoresSafeArea())
            .navigationTitle("Adjust ingredients")
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

    private func quantityBinding(sectionIndex: Int, ingredientIndex: Int) -> Binding<String> {
        Binding(
            get: {
                guard draftSections.indices.contains(sectionIndex),
                      draftSections[sectionIndex].drafts.indices.contains(ingredientIndex) else {
                    return ""
                }
                return draftSections[sectionIndex].drafts[ingredientIndex].quantity
            },
            set: { newValue in
                guard draftSections.indices.contains(sectionIndex),
                      draftSections[sectionIndex].drafts.indices.contains(ingredientIndex) else {
                    return
                }
                draftSections[sectionIndex].drafts[ingredientIndex].quantity = newValue

                guard let target = IngredientQuantityMath.parse(newValue),
                      let base = draftSections[sectionIndex].drafts[ingredientIndex].baseQuantity,
                      base > 0 else {
                    return
                }

                let scale = target / base
                for otherSectionIndex in draftSections.indices {
                    for otherIngredientIndex in draftSections[otherSectionIndex].drafts.indices {
                        guard otherSectionIndex != sectionIndex || otherIngredientIndex != ingredientIndex,
                              let otherBase = draftSections[otherSectionIndex].drafts[otherIngredientIndex].baseQuantity else {
                            continue
                        }
                        draftSections[otherSectionIndex].drafts[otherIngredientIndex].quantity = IngredientQuantityMath.format(
                            otherBase * scale,
                            unit: draftSections[otherSectionIndex].drafts[otherIngredientIndex].unit
                        )
                    }
                }
            }
        )
    }
}

private struct CookingView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let recipe: RecipePublic
    let ingredientSections: [IngredientSection]
    let tint: Color
    @State private var selectedStepIndex = 0
    @State private var completedStepOrders: Set<Int> = []
    @State private var showIngredients = false
    @State private var showCompletion = false
    @State private var hasAppeared = false
    @State private var hasFinalized = false

    init(recipe: RecipePublic, ingredientSections: [IngredientSection], tint: Color) {
        self.recipe = recipe
        self.ingredientSections = ingredientSections
        self.tint = tint

        let validStepOrders = Set(recipe.steps.map(\.order))
        let savedProgress = CookingProgressStore.load(for: recipe.id)
        let savedIndex = savedProgress?.selectedStepIndex ?? 0
        let lastStepIndex = max(recipe.steps.count - 1, 0)

        _selectedStepIndex = State(initialValue: min(max(savedIndex, 0), lastStepIndex))
        _completedStepOrders = State(
            initialValue: Set((savedProgress?.completedStepOrders ?? []).filter { validStepOrders.contains($0) })
        )
    }

    private var sortedSteps: [Step] {
        recipe.steps.sorted { $0.order < $1.order }
    }

    private var currentStepNumber: Int {
        guard !sortedSteps.isEmpty else { return 0 }
        return min(selectedStepIndex, sortedSteps.count - 1) + 1
    }

    private var currentStepIsComplete: Bool {
        guard sortedSteps.indices.contains(selectedStepIndex) else { return false }
        return completedStepOrders.contains(sortedSteps[selectedStepIndex].order)
    }

    private var primaryActionTitle: String {
        currentStepIsComplete && selectedStepIndex == sortedSteps.count - 1 ? "Done" : "Next"
    }

    private var primaryActionImage: String {
        currentStepIsComplete && selectedStepIndex == sortedSteps.count - 1 ? "checkmark" : "arrow.right"
    }

    private var motion: Animation {
        reduceMotion
            ? .linear(duration: 0.01)
            : .spring(response: 0.42, dampingFraction: 0.84)
    }

    private var quickMotion: Animation {
        reduceMotion ? .linear(duration: 0.01) : .easeInOut(duration: 0.22)
    }

    var body: some View {
        VStack(spacing: 0) {
            cookingHeader
                .opacity(hasAppeared ? 1 : 0)
                .offset(y: hasAppeared ? 0 : -8)
                .animation(motion, value: hasAppeared)

            if sortedSteps.isEmpty {
                CookingEmptyState {
                    ReciHaptics.lightImpact()
                    dismiss()
                }
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(Array(sortedSteps.enumerated()), id: \.element.id) { index, step in
                                Button {
                                    selectStep(index)
                                } label: {
                                    CookingStepCard(
                                        step: step,
                                        index: index,
                                        isActive: selectedStepIndex == index,
                                        isComplete: completedStepOrders.contains(step.order),
                                        tint: tint
                                    )
                                }
                                .buttonStyle(.plain)
                                .id(step.id)
                                .opacity(hasAppeared ? 1 : 0)
                                .offset(y: hasAppeared ? 0 : 18)
                                .animation(
                                    motion.delay(reduceMotion ? 0 : 0.06 * Double(index)),
                                    value: hasAppeared
                                )
                            }
                        }
                        .padding(.horizontal, 20)
                        .padding(.top, 8)
                        .padding(.bottom, 16)
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: selectedStepIndex) { _, newValue in
                        guard sortedSteps.indices.contains(newValue) else { return }
                        withAnimation(motion) {
                            proxy.scrollTo(sortedSteps[newValue].id, anchor: .center)
                        }
                    }
                }
            }
        }
        .background(ReciTheme.canvas.ignoresSafeArea())
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if !sortedSteps.isEmpty {
                VStack(spacing: 10) {
                    if showCompletion {
                        completionBanner
                    }
                    cookingActionBar
                }
            }
        }
        .onAppear {
            withAnimation(motion) {
                hasAppeared = true
            }
        }
        .onChange(of: selectedStepIndex) { _, _ in
            persistCookingProgress()
        }
        .onChange(of: completedStepOrders) { _, _ in
            persistCookingProgress()
        }
        .onDisappear {
            persistCookingProgress()
        }
        .sheet(isPresented: $showIngredients) {
            CookingIngredientsSheet(ingredientSections: ingredientSections)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationCornerRadius(32)
                .presentationBackground(ReciTheme.canvas)
        }
    }

    private var cookingHeader: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text(recipe.title)
                    .font(.system(size: 24, weight: .semibold, design: .rounded))
                    .foregroundStyle(ReciTheme.ink)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if !sortedSteps.isEmpty {
                Text("\(currentStepNumber)/\(sortedSteps.count)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(ReciTheme.muted)
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .animation(quickMotion, value: currentStepNumber)
            }

            Button {
                ReciHaptics.lightImpact()
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(ReciTheme.ink)
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .scaleEffect(hasAppeared ? 1 : 0.8)
            .animation(motion.delay(0.08), value: hasAppeared)
            .accessibilityLabel("Close cooking mode")
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
        .padding(.bottom, 10)
    }

    private var cookingActionBar: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                CookingStepBackButton(
                    currentStep: currentStepNumber,
                    totalSteps: sortedSteps.count,
                    action: previousStep
                )

                CookingControlButton(title: "Ingredients", systemImage: "fork.knife") {
                    ReciHaptics.lightImpact()
                    showIngredients = true
                }
            }

            CookingControlButton(
                title: primaryActionTitle,
                systemImage: primaryActionImage,
                isProminent: true,
                action: advanceStep
            )
        }
        .padding(10)
        .background(ReciTheme.canvas.opacity(0.94), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .padding(.horizontal, 14)
        .padding(.bottom, 8)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    private var completionBanner: some View {
        HStack(spacing: 11) {
            Image(systemName: "checkmark.circle.fill")
                .font(.title3.weight(.semibold))
                .foregroundStyle(ReciTheme.green)

            VStack(alignment: .leading, spacing: 2) {
                Text("Recipe complete")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(ReciTheme.ink)
                Text("Nice work. Tap Done to close cooking mode.")
                    .font(.caption)
                    .foregroundStyle(ReciTheme.muted)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .padding(.horizontal, 14)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    private func persistCookingProgress() {
        guard !sortedSteps.isEmpty, !hasFinalized else { return }
        CookingProgressStore.save(
            CookingProgress(
                selectedStepIndex: selectedStepIndex,
                completedStepOrders: completedStepOrders
            ),
            for: recipe.id
        )
    }

    private func selectStep(_ index: Int) {
        guard sortedSteps.indices.contains(index), selectedStepIndex != index else { return }
        ReciHaptics.selection()
        withAnimation(motion) {
            selectedStepIndex = index
            showCompletion = false
        }
    }

    private func previousStep() {
        guard selectedStepIndex > 0 else { return }
        ReciHaptics.selection()
        withAnimation(motion) {
            selectedStepIndex -= 1
            showCompletion = false
        }
    }

    private func advanceStep() {
        guard sortedSteps.indices.contains(selectedStepIndex) else { return }
        let currentStep = sortedSteps[selectedStepIndex]

        if currentStepIsComplete && selectedStepIndex == sortedSteps.count - 1 {
            hasFinalized = true
            CookingProgressStore.clear(for: recipe.id)
            ReciHaptics.success()
            dismiss()
            return
        }

        withAnimation(motion) {
            completedStepOrders.insert(currentStep.order)
        }

        if selectedStepIndex < sortedSteps.count - 1 {
            ReciHaptics.selection()
            withAnimation(motion) {
                selectedStepIndex += 1
            }
        } else {
            ReciHaptics.success()
            withAnimation(motion) {
                showCompletion = true
            }
        }
    }
}

private struct CookingStepCard: View {
    let step: Step
    let index: Int
    let isActive: Bool
    let isComplete: Bool
    let tint: Color
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var restingRotation: Double {
        index.isMultiple(of: 2) ? -0.75 : 0.75
    }

    var body: some View {
        VStack(alignment: .leading, spacing: isActive && step.durationMinutes != nil ? 14 : 9) {
            HStack(spacing: 8) {
                Text(String(format: ReciLocalization.string("Step %d"), step.order))
                    .font(.caption.weight(.bold))
                    .foregroundStyle(isActive ? tint : ReciTheme.muted)
                    .textCase(.uppercase)
                    .tracking(0.8)

                Spacer(minLength: 0)

                if isComplete {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(ReciTheme.green)
                        .transition(.scale.combined(with: .opacity))
                }
            }

            Text(step.text)
                .font(.system(size: 19, weight: isActive ? .medium : .regular, design: .rounded))
                .foregroundStyle(isActive ? ReciTheme.ink : ReciTheme.muted)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)

            if isActive, let minutes = step.durationMinutes {
                Label(String(format: ReciLocalization.string("%dm"), minutes), systemImage: "clock")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ReciTheme.ink)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 10)
                    .background(ReciTheme.canvas, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .transition(.scale(scale: 0.92).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            isActive ? ReciTheme.surface : ReciTheme.line.opacity(0.58),
            in: RoundedRectangle(cornerRadius: 22, style: .continuous)
        )
        .rotationEffect(.degrees(isActive ? 0 : restingRotation))
        .scaleEffect(isActive ? 1 : 0.985)
        .animation(
            reduceMotion ? .linear(duration: 0.01) : .spring(response: 0.4, dampingFraction: 0.82),
            value: isActive
        )
        .animation(
            reduceMotion ? .linear(duration: 0.01) : .spring(response: 0.34, dampingFraction: 0.86),
            value: isComplete
        )
        .padding(.horizontal, 3)
    }
}

private struct CookingControlButton: View {
    let title: String
    let systemImage: String
    var isProminent = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if isProminent {
                    HStack(spacing: 8) {
                        Text(ReciLocalization.string(title))
                        Image(systemName: systemImage)
                    }
                } else {
                    Label(ReciLocalization.string(title), systemImage: systemImage)
                }
            }
                .font(.caption.weight(.bold))
                .foregroundStyle(isProminent ? .white : ReciTheme.ink)
                .padding(.vertical, 14)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(
                    isProminent ? ReciTheme.orange : ReciTheme.surface,
                    in: RoundedRectangle(cornerRadius: 15, style: .continuous)
                )
        }
        .buttonStyle(CookingControlButtonStyle())
        .accessibilityLabel(ReciLocalization.string(title))
        .accessibilityHint(isProminent ? ReciLocalization.string("Advances to the next cooking step.") : "")
    }
}

private struct CookingStepBackButton: View {
    let currentStep: Int
    let totalSteps: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Image(systemName: "chevron.left")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(currentStep > 1 ? ReciTheme.ink : ReciTheme.muted)
            }
            .frame(width: 44, height: 44)
            .background(ReciTheme.surface, in: Circle())
        }
        .buttonStyle(CookingControlButtonStyle())
        .disabled(currentStep <= 1)
        .opacity(currentStep <= 1 ? 0.55 : 1)
        .accessibilityLabel("Previous step")
        .accessibilityValue("Step \(currentStep) of \(totalSteps)")
    }
}

private struct CookingControlButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.93 : 1)
            .opacity(configuration.isPressed ? 0.82 : 1)
            .animation(
                reduceMotion ? .linear(duration: 0.01) : .spring(response: 0.24, dampingFraction: 0.76),
                value: configuration.isPressed
            )
    }
}

private struct CookingEmptyState: View {
    let close: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "list.number")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
                .frame(width: 68, height: 68)
                .background(ReciTheme.orangeSoft, in: Circle())

            VStack(spacing: 5) {
                Text("No steps yet")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(ReciTheme.ink)
                Text("This recipe does not have a method to cook through.")
                    .font(.subheadline)
                    .foregroundStyle(ReciTheme.muted)
                    .multilineTextAlignment(.center)
            }

            Button("Close", action: close)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(.white)
                .padding(.horizontal, 22)
                .padding(.vertical, 12)
                .background(ReciTheme.orange, in: Capsule())
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct CookingIngredientsSheet: View {
    @Environment(\.dismiss) private var dismiss
    let ingredientSections: [IngredientSection]

    private var ingredientCount: Int {
        ingredientSections.reduce(0) { $0 + $1.ingredients.count }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                ReciTheme.canvas.ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text("Ingredients")
                                .font(.system(size: 30, weight: .bold, design: .rounded))
                                .foregroundStyle(ReciTheme.ink)

                            Text("\(ingredientCount)")
                                .font(.caption.weight(.bold))
                                .foregroundStyle(ReciTheme.orange)
                                .padding(.horizontal, 9)
                                .padding(.vertical, 5)
                                .background(ReciTheme.orangeSoft, in: Capsule())
                        }

                        Text("Everything you need, ready to check while you cook.")
                            .font(.subheadline)
                            .foregroundStyle(ReciTheme.muted)
                            .fixedSize(horizontal: false, vertical: true)

                        if ingredientCount == 0 {
                            VStack(spacing: 10) {
                                Image(systemName: "fork.knife")
                                    .font(.title3.weight(.semibold))
                                    .foregroundStyle(ReciTheme.orange)
                                Text("No ingredients listed")
                                    .font(.headline)
                                    .foregroundStyle(ReciTheme.ink)
                                Text("This recipe does not include an ingredient list.")
                                    .font(.subheadline)
                                    .foregroundStyle(ReciTheme.muted)
                                    .multilineTextAlignment(.center)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 28)
                            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                        } else {
                            VStack(alignment: .leading, spacing: 14) {
                                ForEach(Array(ingredientSections.enumerated()), id: \.offset) { sectionIndex, section in
                                    VStack(alignment: .leading, spacing: 8) {
                                        if ingredientSections.count > 1 || section.title != "Ingredients" {
                                            Text(section.title)
                                                .font(.subheadline.weight(.bold))
                                                .foregroundStyle(ReciTheme.ink)
                                                .padding(.horizontal, 4)
                                        }

                                        VStack(spacing: 0) {
                                            ForEach(Array(section.ingredients.enumerated()), id: \.offset) { ingredientIndex, ingredient in
                                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                                    Circle()
                                                        .fill(ReciTheme.orange)
                                                        .frame(width: 7, height: 7)

                                                    Text(ingredient.quantity ?? "—")
                                                        .font(.subheadline.weight(.semibold))
                                                        .foregroundStyle(ReciTheme.ink)
                                                        .monospacedDigit()
                                                        .frame(width: 58, alignment: .trailing)

                                                    Text(ingredient.unit ?? "")
                                                        .font(.caption.weight(.semibold))
                                                        .foregroundStyle(ReciTheme.muted)
                                                        .lineLimit(1)
                                                        .minimumScaleFactor(0.72)
                                                        .frame(width: 72, alignment: .leading)

                                                    Text(ingredient.name)
                                                        .font(.body)
                                                        .foregroundStyle(ReciTheme.ink)
                                                        .frame(maxWidth: .infinity, alignment: .leading)
                                                        .fixedSize(horizontal: false, vertical: true)
                                                }
                                                .padding(.horizontal, 16)
                                                .padding(.vertical, 15)
                                                .background(
                                                    (sectionIndex + ingredientIndex).isMultiple(of: 2)
                                                        ? ReciTheme.surface
                                                        : ReciTheme.surface.opacity(0.72)
                                                )
                                            }
                                        }
                                        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                                    }
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 18)
                    .padding(.bottom, 32)
                }
            }
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                }
            }
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
