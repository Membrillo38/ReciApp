import Foundation

@MainActor
final class AppViewModel: ObservableObject {
    @Published var me: MeResponse?
    @Published var recipes: [RecipeSummary] = []
    @Published var recipeCategories: [UUID: String] = [:]
    @Published var customCategories: [String] = []
    @Published var isLoading = false
    @Published var isImporting = false
    @Published var importProgress = 0
    @Published var importURL = ""
    @Published var statusMessage = ""
    @Published var errorMessage: String?
    @Published var lastImportedRecipe: RecipePublic?
    @Published var selectedRecipe: RecipePublic?

    private let api = APIClient()
    private weak var auth: AuthService?
    private var pendingImportURL: String?
    private let categoriesKey = "reciapp.recipeCategories.v1"
    private let customCategoriesKey = "reciapp.customCategories.v1"
    static let uncategorized = "Uncategorized"

    init() {
        loadLocalCategories()
    }

    func bind(auth: AuthService) {
        self.auth = auth
    }

    var token: String? { auth?.accessToken }

    var planLabel: String {
        if me?.isPro == true { return "Pro" }
        return "Free"
    }

    func pasteFromClipboard() {
        #if os(iOS)
        if let s = UIPasteboard.general.string {
            importURL = s
        }
        #endif
    }

    func pasteAndImport() async {
        pasteFromClipboard()
        await importRecipe()
    }

    func refreshAll() async {
        guard let token else { return }
        AppLogger.app.info("refresh started")
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await ensureDevPro(token: token)
            me = try await api.me(token: token)
            recipes = try await api.myRecipes(token: token)
            reconcileLocalRecipeIds()
            AppLogger.app.info("refresh completed recipes=\(self.recipes.count, privacy: .public)")
        } catch {
            errorMessage = error.localizedDescription
            AppLogger.app.error("refresh failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Accept raw share text / URL from paste, open URL, etc.
    func importFromRaw(_ raw: String) async {
        guard let normalized = URLNormalizer.normalize(raw) else {
            errorMessage = "Unsupported or invalid URL. TikTok, YouTube, Instagram, Facebook only."
            return
        }
        importURL = normalized
        guard token != nil else {
            pendingImportURL = normalized
            statusMessage = "sign in to import"
            return
        }
        await importRecipe()
    }

    func flushPendingImport() async {
        guard let pending = pendingImportURL, token != nil else { return }
        pendingImportURL = nil
        importURL = pending
        await importRecipe()
    }

    func importRecipe() async {
        guard let token else {
            errorMessage = "Not signed in"
            return
        }

        guard let normalized = URLNormalizer.normalize(importURL) else {
            errorMessage = "Unsupported or invalid URL"
            return
        }

        isLoading = true
        isImporting = true
        errorMessage = nil
        statusMessage = "starting…"
        importProgress = 1
        AppLogger.app.info("import started host=\(URL(string: normalized)?.host ?? "unknown", privacy: .public)")
        defer {
            isLoading = false
            isImporting = false
        }

        do {
            try await ensureDevPro(token: token)
            let recipe = try await api.extractAndWait(url: normalized, token: token) { [weak self] status, progress in
                Task { @MainActor in
                    self?.statusMessage = status
                    self?.importProgress = progress
                }
            }
            setCategory(AppViewModel.uncategorized, for: recipe.id)
            lastImportedRecipe = recipe
            selectedRecipe = recipe
            importURL = ""
            statusMessage = "done: \(recipe.title)"
            importProgress = 100
            AppLogger.app.info("import completed recipeId=\(recipe.id.uuidString, privacy: .public)")
            await refreshAll()
        } catch let err as AppError {
            statusMessage = ""
            importProgress = 0
            switch err {
            case .quota(let d):
                if d.code == "FREE_WEEKLY_LIMIT" {
                    errorMessage = "\(d.message) (check Secrets.adminApiKey for dev Pro)"
                } else {
                    errorMessage = d.message
                }
            default:
                errorMessage = err.localizedDescription
            }
        } catch {
            statusMessage = ""
            importProgress = 0
            errorMessage = error.localizedDescription
            AppLogger.app.error("import failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    func openRecipe(_ summary: RecipeSummary) async {
        guard let token else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            selectedRecipe = try await api.recipe(id: summary.id, token: token)
            AppLogger.app.info("recipe loaded id=\(summary.id.uuidString, privacy: .public)")
        } catch {
            errorMessage = error.localizedDescription
            AppLogger.app.error("recipe load failed id=\(summary.id.uuidString, privacy: .public): \(error.localizedDescription, privacy: .public)")
        }
    }

    func deleteRecipe(_ summary: RecipeSummary) async {
        guard let token else { return }
        do {
            try await api.deleteRecipe(id: summary.id, token: token)
            if selectedRecipe?.id == summary.id { selectedRecipe = nil }
            recipeCategories.removeValue(forKey: summary.id)
            saveLocalCategories()
            await refreshAll()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteAccount() async {
        guard let token else { return }
        do {
            try await api.deleteAccount(token: token)
            await auth?.signOut()
            me = nil
            recipes = []
            recipeCategories = [:]
            customCategories = []
            saveLocalCategories()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var allCategoryNames: [String] {
        var names = Set(customCategories)
        names.formUnion(recipeCategories.values)
        names.insert(Self.uncategorized)
        return names.sorted { lhs, rhs in
            if lhs == Self.uncategorized { return true }
            if rhs == Self.uncategorized { return false }
            return lhs.localizedCaseInsensitiveCompare(rhs) == .orderedAscending
        }
    }

    func category(for recipeId: UUID) -> String {
        recipeCategories[recipeId] ?? Self.uncategorized
    }

    func recipes(in category: String) -> [RecipeSummary] {
        recipes.filter { self.category(for: $0.id) == category }
    }

    func categoryCounts() -> [RecipeCategoryFolder] {
        allCategoryNames
            .map { RecipeCategoryFolder(name: $0, count: recipes(in: $0).count) }
            .filter { $0.count > 0 || customCategories.contains($0.name) || $0.name == Self.uncategorized }
    }

    func addCategory(_ name: String) {
        let clean = cleanCategoryName(name)
        guard !clean.isEmpty, clean != Self.uncategorized else { return }
        if !customCategories.contains(clean) {
            customCategories.append(clean)
            customCategories.sort { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
            saveLocalCategories()
        }
    }

    func setCategory(_ name: String, for recipeId: UUID) {
        let clean = cleanCategoryName(name)
        let category = clean.isEmpty ? Self.uncategorized : clean
        if category != Self.uncategorized {
            addCategory(category)
        }
        recipeCategories[recipeId] = category
        saveLocalCategories()
    }

    private func ensureDevPro(token: String) async throws {
        guard DevConfig.autoGrantPro, let key = Secrets.adminApiKey else { return }
        let current = try await api.me(token: token)
        if !current.isPro {
            try await api.grantPro(userId: current.id, adminKey: key)
        }
    }

    private func loadLocalCategories() {
        let defaults = UserDefaults.standard
        if let raw = defaults.dictionary(forKey: categoriesKey) as? [String: String] {
            recipeCategories = raw.reduce(into: [:]) { partial, item in
                if let id = UUID(uuidString: item.key) {
                    partial[id] = item.value
                }
            }
        }
        customCategories = defaults.stringArray(forKey: customCategoriesKey) ?? []
    }

    private func saveLocalCategories() {
        let raw = recipeCategories.reduce(into: [String: String]()) { partial, item in
            partial[item.key.uuidString] = item.value
        }
        UserDefaults.standard.set(raw, forKey: categoriesKey)
        UserDefaults.standard.set(customCategories, forKey: customCategoriesKey)
    }

    private func reconcileLocalRecipeIds() {
        let liveIds = Set(recipes.map(\.id))
        var changed = false
        for id in recipeCategories.keys where !liveIds.contains(id) {
            recipeCategories.removeValue(forKey: id)
            changed = true
        }
        for id in liveIds where recipeCategories[id] == nil {
            recipeCategories[id] = Self.uncategorized
            changed = true
        }
        if changed {
            saveLocalCategories()
        }
    }

    private func cleanCategoryName(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

#if os(iOS)
import UIKit
#endif
