import Foundation

@MainActor
final class AppViewModel: ObservableObject {
    @Published var me: MeResponse?
    @Published var recipes: [RecipeSummary] = []
    @Published var recipeCategories: [UUID: String] = [:]
    @Published var customCategories: [String] = []
    @Published var categoryColors: [String: String] = [:]
    @Published var favoriteIDs: Set<UUID> = []
    @Published var recipeTags: [UUID: [String]] = [:]
    @Published var categoryParents: [String: String] = [:]
    @Published private(set) var folderSortRawValue = FolderSort.created.rawValue
    @Published private(set) var folderColumns = 2
    @Published private(set) var folderLayoutRawValue = CollectionLayout.grid.rawValue
    @Published private(set) var recipeLayoutRawValue = CollectionLayout.grid.rawValue
    @Published private(set) var recipeColumns = 2
    @Published var isLoading = false
    @Published var isImporting = false
    @Published var importProgress = 0
    @Published var importQueuePosition = 0
    @Published var importQueueTotal = 0
    @Published var importQueueHosts: [String] = []
    @Published var importURL = ""
    @Published var statusMessage = ""
    @Published var errorMessage: String?
    @Published var organizationErrorMessage: String?
    @Published var lastImportedRecipe: RecipePublic?
    @Published var selectedRecipe: RecipePublic?
    @Published var selectedRecipeSummary: RecipeSummary?
    @Published var refreshedDetail: RecipePublic?
    @Published var canResumeImport = false
    @Published private(set) var groupedRecipesCache: [String: [RecipeSummary]] = [:]
    @Published private(set) var categoryFoldersCache: [RecipeCategoryFolder] = []

    private var api: APIClient { auth?.api ?? APIClient() }
    private weak var auth: AuthService?
    private var libraryTasks = SharedTaskCoordinator<String, [RecipeSummary], Error>()
    private var profileTasks = SharedTaskCoordinator<String, MeResponse, Error>()
    private var detailTasks = SharedTaskCoordinator<String, RecipePublic, Error>()
    private var detailRevalidationPolicy = DetailRevalidationPolicy()
    private var importTask: (id: UUID, task: Task<Void, Error>)?
    private var lastServerQueue: [QueuedJobItem] = []
    private var generation = 0
    private var lastForegroundRefresh: Date?
    private var subscriptionRefreshGeneration = 0
    private var consumedShareIDs = Set<UUID>()
    private var activeRecipeCacheIdentity: String?
    private var activeUserID: UUID?
    private var recipeDetailsCache: [UUID: RecipePublic] = [:]
    private let pendingImportKey = "reciapp.pendingImportURL.v1"
    private let recipeCacheKeyPrefix = "reciapp.recipeCache.v3"
    private let migrationKey = CacheMigrationPolicy.marker
    static let uncategorized = "Uncategorized"
    static let categoryNameMaxLength = 20
    private static let debugRecipeSourcePrefix = "https://example.com/reciapp-debug/"
    private static let debugPerformanceFolderPrefix = "Performance "
    private let categoryPalette = ["0A84FF", "34C759", "FFC107", "FF5FA2", "FF7119", "A56BFF"]

    private struct RecipeCacheSnapshot: Codable {
        let recipes: [RecipeSummary]
        let recipeDetails: [RecipePublic]
        let savedAt: Date
    }

    private struct FolderCacheSnapshot: Codable {
        let recipeCategories: [String: String]
        let customCategories: [String]
        let categoryColors: [String: String]
        let categoryParents: [String: String]?
        let favoriteIDs: [String]
        let recipeTags: [String: [String]]
        let folderSortRawValue: String?
        let folderColumns: Int?
        let folderLayoutRawValue: String?
        let recipeLayoutRawValue: String?
        let recipeColumns: Int?

        init(
            recipeCategories: [String: String],
            customCategories: [String],
            categoryColors: [String: String],
            categoryParents: [String: String]?,
            favoriteIDs: [String] = [],
            recipeTags: [String: [String]] = [:],
            folderSortRawValue: String? = nil,
            folderColumns: Int? = nil,
            folderLayoutRawValue: String? = nil,
            recipeLayoutRawValue: String? = nil,
            recipeColumns: Int? = nil
        ) {
            self.recipeCategories = recipeCategories
            self.customCategories = customCategories
            self.categoryColors = categoryColors
            self.categoryParents = categoryParents
            self.favoriteIDs = favoriteIDs
            self.recipeTags = recipeTags
            self.folderSortRawValue = folderSortRawValue
            self.folderColumns = folderColumns
            self.folderLayoutRawValue = folderLayoutRawValue
            self.recipeLayoutRawValue = recipeLayoutRawValue
            self.recipeColumns = recipeColumns
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            recipeCategories = try container.decode([String: String].self, forKey: .recipeCategories)
            customCategories = try container.decode([String].self, forKey: .customCategories)
            categoryColors = try container.decode([String: String].self, forKey: .categoryColors)
            categoryParents = try container.decodeIfPresent([String: String].self, forKey: .categoryParents)
            favoriteIDs = try container.decodeIfPresent([String].self, forKey: .favoriteIDs) ?? []
            recipeTags = try container.decodeIfPresent([String: [String]].self, forKey: .recipeTags) ?? [:]
            folderSortRawValue = try container.decodeIfPresent(String.self, forKey: .folderSortRawValue)
            folderColumns = try container.decodeIfPresent(Int.self, forKey: .folderColumns)
            folderLayoutRawValue = try container.decodeIfPresent(String.self, forKey: .folderLayoutRawValue)
            recipeLayoutRawValue = try container.decodeIfPresent(String.self, forKey: .recipeLayoutRawValue)
            recipeColumns = try container.decodeIfPresent(Int.self, forKey: .recipeColumns)
        }
    }

    init() {
        removeLegacyCachesOnce()
        rebuildFolderCache()
    }

    func bind(auth: AuthService) {
        self.auth = auth
        SubscriptionService.shared.configure()
        SubscriptionService.shared.onEntitlementChange = { [weak self] in
            Task { @MainActor in
                await self?.refreshSubscriptionState()
            }
        }
    }

    func dismissError() {
        errorMessage = nil
    }

    func markImportedRecipeSeen(_ id: UUID) {
        guard lastImportedRecipe?.id == id else { return }
        lastImportedRecipe = nil
    }

    func warmUpBackend() async {
        await APIClient.warmUpBackend()
    }

    #if DEBUG
    func loadDesignPreview() {
        guard ProcessInfo.processInfo.arguments.contains("-reciapp-design-preview") else { return }
        let sampleRecipes = [
            RecipeSummary(
                id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000001")!,
                title: "Creamy tomato pasta",
                platform: "Instagram",
                sourceUrl: "https://example.com/pasta",
                thumbnailUrl: "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?auto=format&fit=crop&w=900&q=85",
                author: "ReciApp",
                servings: 2,
                prepMinutes: 10,
                cookMinutes: 20,
                savedAt: ""
            ),
            RecipeSummary(
                id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000002")!,
                title: "Crispy chicken bowl",
                platform: "TikTok",
                sourceUrl: "https://example.com/chicken",
                thumbnailUrl: "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=900&q=85",
                author: "ReciApp",
                servings: 4,
                prepMinutes: 15,
                cookMinutes: 25,
                savedAt: ""
            ),
            RecipeSummary(
                id: UUID(uuidString: "5F7D5712-ABCD-4C70-8EEE-000000000003")!,
                title: "Roasted vegetables",
                platform: "YouTube",
                sourceUrl: "https://example.com/vegetables",
                thumbnailUrl: "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?auto=format&fit=crop&w=900&q=85",
                author: "ReciApp",
                servings: 3,
                prepMinutes: 8,
                cookMinutes: 30,
                savedAt: ""
            ),
        ]
        recipes = sampleRecipes
        customCategories = ["Weeknight", "Quick"]
        categoryColors = ["Weeknight": "F2C94C", "Quick": "34C759"]
        categoryParents = ["Quick": "Weeknight"]
        recipeCategories = [
            sampleRecipes[0].id: "Weeknight",
            sampleRecipes[1].id: "Quick",
            sampleRecipes[2].id: Self.uncategorized,
        ]
        rebuildFolderCache()
    }
    #else
    func loadDesignPreview() {}
    #endif

    var token: String? { auth?.accessToken }

    var planLabel: String {
        if me?.isPro == true { return ReciLocalization.string("Pro") }
        return ReciLocalization.string("Free")
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
        await importFromRaw(importURL)
    }

    func refreshAll(force: Bool = false) async {
        guard let userID = auth?.session?.user.id, token != nil else { return }
        activate(userID: userID, language: AppLanguageStore.current.serverCode)
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        let language = AppLanguageStore.current.serverCode
        if force { lastForegroundRefresh = Date() }

        isLoading = true
        errorMessage = nil
        AppLogger.app.info("refresh started cachedRecipes=\(self.recipes.count, privacy: .public)")
        defer { if expectedGeneration == generation { isLoading = false } }

        async let libraryResult = capture { try await self.sharedLibrary(language: language) }
        async let profileResult = capture { try await self.sharedProfile() }
        let (library, profile) = await (libraryResult, profileResult)

        guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: userID) else { return }
        if case .success(let fetchedRecipes) = library {
            recipes = CacheRefreshPolicy.library(cached: recipes, successfulResponse: fetchedRecipes)
            reconcileLocalRecipeIds(pruneMissing: true)
            rebuildFolderCache()
            persistRecipeCache()
            AppLogger.app.info("recipe refresh completed recipes=\(self.recipes.count, privacy: .public)")
        } else if case .failure(let error) = library {
            AppLogger.app.error("recipe refresh failed cachedRecipes=\(self.recipes.count, privacy: .public): \(error.localizedDescription, privacy: .public)")
            if recipes.isEmpty { errorMessage = error.localizedDescription }
        }

        if case .success(let fetchedMe) = profile {
            me = fetchedMe
            SubscriptionService.shared.identify(userID: fetchedMe.id)
            AppLogger.app.info("profile refresh completed")
        } else if case .failure(let error) = profile {
            AppLogger.app.error("profile refresh failed: \(error.localizedDescription, privacy: .public)")
            if isUnauthorized(error) {
                await auth?.signOut()
            }
        }

        if case .failure(let error) = library, isUnauthorized(error) {
            await auth?.signOut()
        }
    }

    func refreshForForeground(now: Date = Date()) async {
        if let lastForegroundRefresh, now.timeIntervalSince(lastForegroundRefresh) < 30 { return }
        lastForegroundRefresh = now
        await refreshAll()
    }

    /// Accept raw share text / URL from paste, open URL, etc.
    func importFromRaw(_ raw: String, language: String? = nil, deliveryID: UUID? = nil) async {
        if let deliveryID, !consumedShareIDs.insert(deliveryID).inserted { return }

        let language = language ?? AppLanguageStore.current.serverCode
        let urls = URLNormalizer.normalizeAll(raw)
        guard !urls.isEmpty else {
            // Invalid payload: drop this delivery so it does not block the inbox.
            if let deliveryID { ShareInbox.markProcessed(deliveryID) }
            errorMessage = ReciLocalization.string("Unsupported or invalid URL. TikTok, YouTube, Instagram, Facebook only.")
            return
        }

        var newURLs: [String] = []
        for url in urls {
            if let existing = existingLibraryRecipe(matching: url) {
                if let deliveryID { ShareInbox.markProcessed(deliveryID) }
                openExistingRecipe(existing)
                continue
            }
            newURLs.append(url)
        }
        guard !newURLs.isEmpty else { return }

        for url in newURLs {
            ShareInbox.enqueue(raw: url, language: language)
        }
        importURL = newURLs[0]
        updateQueuePreview()

        guard token != nil else {
            statusMessage = ReciLocalization.string("sign in to import")
            return
        }
        await submitShareInboxAndFollow(language: language)
    }

    private func existingLibraryRecipe(matching url: String) -> RecipeSummary? {
        let normalized = URLNormalizer.normalize(url) ?? url
        return recipes.first { recipe in
            let candidate = URLNormalizer.normalize(recipe.sourceUrl) ?? recipe.sourceUrl
            return candidate == normalized
        }
    }

    private func openExistingRecipe(_ summary: RecipeSummary) {
        if let cached = recipeDetailsCache[summary.id] {
            selectedRecipe = cached
            lastImportedRecipe = nil
        } else {
            selectedRecipeSummary = summary
            lastImportedRecipe = nil
        }
        statusMessage = ""
        importProgress = 0
    }

    func importFromIncomingURL(_ url: URL) async {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        let deliveryID = items?.first(where: { $0.name == "id" })?.value.flatMap(UUID.init(uuidString:))
        let raw: String
        if url.scheme?.lowercased() == "reciapp" {
            raw = items?.first(where: { $0.name == "url" })?.value ?? ""
        } else {
            raw = url.absoluteString
        }
        // Extension already enqueued all URLs; deep link wakes the app to drain.
        await importFromRaw(raw, deliveryID: deliveryID)
    }

    func flushPendingImport() async {
        if let legacy = UserDefaults.standard.string(forKey: pendingImportKey) {
            UserDefaults.standard.removeObject(forKey: pendingImportKey)
            ShareInbox.enqueue(raw: legacy, language: AppLanguageStore.current.serverCode)
        }
        await resumePersistedJobIfNeeded()
        await drainShareInbox()
    }

    func drainShareInbox() async {
        guard token != nil else { return }
        await submitShareInboxAndFollow(language: AppLanguageStore.current.serverCode)
    }

    func resumePersistedJobIfNeeded() async {
        guard !isImporting, importTask == nil, token != nil, let userID = activeUserID,
              ImportJobStore.load(userID: userID) != nil else { return }
        await resumeImport()
    }

    /// Submit every inbox URL to the server (creates pending jobs), then follow the serial queue.
    private func submitShareInboxAndFollow(language: String) async {
        _ = await submitShareInbox(language: language)
        guard !isImporting, importTask == nil else {
            updateQueuePreview()
            return
        }
        await followImportQueue()
    }

    private enum InboxSubmitOutcome {
        case drained
        case retryLater
        case stopped
    }

    @discardableResult
    private func submitShareInbox(language: String) async -> InboxSubmitOutcome {
        guard token != nil else { return .stopped }
        guard let expectedUserID = activeUserID else { return .stopped }
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity

        for delivery in ShareInbox.takeUnprocessed() {
            if let existing = existingLibraryRecipe(matching: delivery.url) {
                ShareInbox.markProcessed(delivery.id)
                openExistingRecipe(existing)
                continue
            }
            do {
                let started = try await api.extract(url: delivery.url, language: delivery.language)
                ShareInbox.markProcessed(delivery.id)
                ImportJobStore.save(
                    PersistedImportJob(
                        jobID: started.jobId,
                        language: delivery.language,
                        userID: expectedUserID,
                        sourceURL: delivery.url
                    )
                )
                // Cache hits complete immediately and never appear in /v1/me/jobs.
                if started.cacheHit || started.status == "completed" {
                    let recipe = try await waitForPersistedJob(
                        PersistedImportJob(
                            jobID: started.jobId,
                            language: delivery.language,
                            userID: expectedUserID,
                            sourceURL: delivery.url
                        ),
                        expectedGeneration: expectedGeneration,
                        expectedIdentity: expectedIdentity,
                        expectedUserID: expectedUserID
                    )
                    if recipes.contains(where: { $0.id == recipe.id }) {
                        openExistingRecipe(
                            RecipeSummary(
                                id: recipe.id,
                                title: recipe.title,
                                platform: recipe.platform,
                                sourceUrl: recipe.sourceUrl,
                                thumbnailUrl: recipe.thumbnailUrl,
                                author: recipe.author,
                                servings: recipe.servings,
                                prepMinutes: recipe.prepMinutes,
                                cookMinutes: recipe.cookMinutes,
                                savedAt: "",
                                languageCode: recipe.languageCode
                            )
                        )
                        ImportJobStore.clear(userID: expectedUserID)
                        continue
                    }
                    try await finishImport(
                        recipe,
                        expectedGeneration: expectedGeneration,
                        expectedIdentity: expectedIdentity,
                        expectedUserID: expectedUserID,
                        continueQueue: true
                    )
                }
            } catch is CancellationError {
                updateQueuePreview()
                return .stopped
            } catch {
                switch queueDisposition(for: error) {
                case .retryLater:
                    if let appError = error as? AppError, case .rateLimited(_, let retryAfter) = appError {
                        try? await Task.sleep(for: .seconds(RetryAfterPolicy.delaySeconds(retryAfter: retryAfter)))
                    }
                    updateQueuePreview()
                    return .retryLater
                case .skipItem:
                    ShareInbox.markProcessed(delivery.id)
                    continue
                case .failItem:
                    ShareInbox.markProcessed(delivery.id)
                    ImportJobStore.clear(userID: expectedUserID)
                    errorMessage = error.localizedDescription
                    continue
                case .stopForUser:
                    if isUnauthorized(error) {
                        presentImportError(error, userID: expectedUserID)
                    } else if let appError = error as? AppError {
                        applyImportAction(appError)
                    } else {
                        presentImportError(error, userID: expectedUserID)
                    }
                    updateQueuePreview()
                    return .stopped
                }
            }
        }
        updateQueuePreview()
        return .drained
    }

    private func followImportQueue() async {
        guard token != nil, !isImporting, importTask == nil else { return }
        guard let expectedUserID = activeUserID else { return }
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        let language = AppLanguageStore.current.serverCode

        // Probe first so empty launches never flash the "Reading…" card.
        let hasLocalPending = !ShareInbox.takeUnprocessed().isEmpty
            || ImportJobStore.load(userID: expectedUserID) != nil
        var openJobs: [QueuedJobItem] = []
        do {
            openJobs = try await api.myJobs().items
        } catch is CancellationError {
            return
        } catch {
            guard hasLocalPending else { return }
            switch queueDisposition(for: error) {
            case .stopForUser:
                presentImportError(error, userID: expectedUserID)
                return
            case .retryLater, .failItem, .skipItem:
                break
            }
        }
        guard hasLocalPending || !openJobs.isEmpty else {
            updateQueuePreview()
            return
        }

        applyQueueSnapshot(openJobs)
        isImporting = true
        canResumeImport = false
        errorMessage = nil
        let importTaskID = UUID()
        defer {
            if importTask?.id == importTaskID { importTask = nil }
            if expectedGeneration == generation, expectedIdentity == activeRecipeCacheIdentity {
                isImporting = false
            }
            updateQueuePreview()
        }

        do {
            let task = Task<Void, Error> {
                try await self.drainServerQueue(
                    language: language,
                    userID: expectedUserID,
                    expectedGeneration: expectedGeneration,
                    expectedIdentity: expectedIdentity
                )
            }
            importTask = (id: importTaskID, task: task)
            try await task.value
        } catch is CancellationError {
            return
        } catch {
            guard scopeIsCurrent(
                generation: expectedGeneration,
                identity: expectedIdentity,
                userID: expectedUserID
            ) else { return }
            presentImportError(error, userID: expectedUserID)
        }
    }

    private func drainServerQueue(
        language: String,
        userID: UUID,
        expectedGeneration: Int,
        expectedIdentity: String?
    ) async throws {
        var backoffAttempt = 0
        var allowSubmit = true
        while true {
            try Task.checkCancellation()
            if allowSubmit {
                switch await submitShareInbox(language: language) {
                case .stopped:
                    allowSubmit = false
                case .retryLater, .drained:
                    break
                }
            }

            let queue: [QueuedJobItem]
            do {
                queue = try await api.myJobs().items
                backoffAttempt = queue.isEmpty ? backoffAttempt : 0
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                switch queueDisposition(for: error) {
                case .retryLater, .failItem, .skipItem:
                    backoffAttempt += 1
                    await markImportWaitingForConnection()
                    try await Task.sleep(for: .seconds(ImportQueueDrainPolicy.backoffSeconds(attempt: backoffAttempt)))
                    continue
                case .stopForUser:
                    throw error
                }
            }

            await MainActor.run {
                guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: userID) else { return }
                self.applyQueueSnapshot(queue)
            }

            let inboxRemaining = allowSubmit && !ShareInbox.takeUnprocessed().isEmpty
            if queue.isEmpty {
                if let persisted = ImportJobStore.load(userID: userID) {
                    let advanced = try await followPersistedJob(
                        persisted,
                        userID: userID,
                        expectedGeneration: expectedGeneration,
                        expectedIdentity: expectedIdentity
                    )
                    if advanced {
                        backoffAttempt = 0
                        try await Task.sleep(for: .seconds(0.5))
                    } else {
                        backoffAttempt += 1
                        await markImportWaitingForConnection()
                        try await Task.sleep(for: .seconds(ImportQueueDrainPolicy.backoffSeconds(attempt: backoffAttempt)))
                    }
                    continue
                }
                if inboxRemaining {
                    backoffAttempt += 1
                    await markImportWaitingForConnection()
                    try await Task.sleep(for: .seconds(ImportQueueDrainPolicy.backoffSeconds(attempt: backoffAttempt)))
                    continue
                }
                return
            }

            let current = queue.first(where: { $0.status == "processing" }) ?? queue[0]
            let record = PersistedImportJob(
                jobID: current.jobId,
                language: language,
                userID: userID,
                sourceURL: current.sourceUrl
            )
            ImportJobStore.save(record)
            await MainActor.run {
                guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: userID) else { return }
                self.statusMessage = Self.localizedImportStatus(current.status)
                self.importProgress = max(current.progress, 1)
                self.importURL = current.sourceUrl
            }

            let advanced = try await followPersistedJob(
                record,
                userID: userID,
                expectedGeneration: expectedGeneration,
                expectedIdentity: expectedIdentity
            )
            if advanced {
                backoffAttempt = 0
                try await Task.sleep(for: .seconds(0.5))
            } else {
                backoffAttempt += 1
                await markImportWaitingForConnection()
                try await Task.sleep(for: .seconds(ImportQueueDrainPolicy.backoffSeconds(attempt: backoffAttempt)))
            }
        }
    }

    /// Returns false when the job stayed on disk and should be retried after backoff.
    private func followPersistedJob(
        _ record: PersistedImportJob,
        userID: UUID,
        expectedGeneration: Int,
        expectedIdentity: String?
    ) async throws -> Bool {
        do {
            let recipe = try await waitForPersistedJob(
                record,
                expectedGeneration: expectedGeneration,
                expectedIdentity: expectedIdentity,
                expectedUserID: userID
            )
            try await finishImport(
                recipe,
                expectedGeneration: expectedGeneration,
                expectedIdentity: expectedIdentity,
                expectedUserID: userID,
                continueQueue: true
            )
            return true
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            switch queueDisposition(for: error) {
            case .retryLater:
                return false
            case .failItem, .skipItem:
                ImportJobStore.clear(userID: userID)
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                }
                return true
            case .stopForUser:
                throw error
            }
        }
    }

    private func queueDisposition(for error: Error) -> ImportQueueErrorPolicy.Disposition {
        if error is CancellationError { return .stopForUser }
        if let appError = error as? AppError {
            return ImportQueueErrorPolicy.disposition(
                status: Self.statusCode(for: appError),
                code: Self.errorCode(for: appError)
            )
        }
        if ImportJobRetentionPolicy.shouldRetryTransport(error) {
            return .retryLater
        }
        return .failItem
    }

    private func markImportWaitingForConnection() async {
        await MainActor.run {
            canResumeImport = false
            statusMessage = ReciLocalization.string("Waiting for connection…")
        }
    }

    private func applyQueueSnapshot(_ queue: [QueuedJobItem]) {
        lastServerQueue = queue
        let pending = ShareInbox.takeUnprocessed()
        importQueueTotal = queue.count + pending.count
        if let processing = queue.first(where: { $0.status == "processing" }) {
            importQueuePosition = processing.queuePosition
        } else if !queue.isEmpty {
            importQueuePosition = queue.first?.queuePosition ?? 0
        } else {
            importQueuePosition = pending.isEmpty ? 0 : 1
        }
        var hosts = queue.compactMap { URL(string: $0.sourceUrl)?.host }
        hosts.append(contentsOf: pending.compactMap { URL(string: $0.url)?.host })
        importQueueHosts = hosts
    }

    private func updateQueuePreview() {
        applyQueueSnapshot(isImporting ? lastServerQueue : [])
    }

    func importRecipe(language: String? = nil) async {
        let raw = importURL
        if URLNormalizer.normalizeAll(raw).count > 1 || !ShareInbox.takeUnprocessed().isEmpty {
            await importFromRaw(raw, language: language)
            return
        }
        guard !isImporting, importTask == nil else {
            if let normalized = URLNormalizer.normalize(importURL) {
                if let existing = existingLibraryRecipe(matching: normalized) {
                    openExistingRecipe(existing)
                    return
                }
                ShareInbox.enqueue(raw: normalized, language: language ?? AppLanguageStore.current.serverCode)
                updateQueuePreview()
            }
            return
        }
        guard token != nil else {
            errorMessage = ReciLocalization.string("Not signed in")
            return
        }

        guard let normalized = URLNormalizer.normalize(importURL) else {
            errorMessage = ReciLocalization.string("Unsupported or invalid URL")
            return
        }

        if let existing = existingLibraryRecipe(matching: normalized) {
            openExistingRecipe(existing)
            return
        }

        ShareInbox.enqueue(raw: normalized, language: language ?? AppLanguageStore.current.serverCode)
        await submitShareInboxAndFollow(language: language ?? AppLanguageStore.current.serverCode)
    }

    func resumeImport() async {
        guard !isImporting, importTask == nil else { return }
        guard token != nil, let expectedUserID = activeUserID,
              let job = ImportJobStore.load(userID: expectedUserID) else { return }

        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        isLoading = true
        isImporting = true
        canResumeImport = false
        errorMessage = nil
        statusMessage = ReciLocalization.string("resuming…")
        importProgress = max(importProgress, 1)
        let importTaskID = UUID()
        defer {
            if importTask?.id == importTaskID { importTask = nil }
            if expectedGeneration == generation, expectedIdentity == activeRecipeCacheIdentity {
                isLoading = false
                isImporting = false
            }
        }

        do {
            let task = Task<Void, Error> {
                let recipe = try await self.waitForPersistedJob(
                    job,
                    expectedGeneration: expectedGeneration,
                    expectedIdentity: expectedIdentity,
                    expectedUserID: expectedUserID
                )
                try await self.finishImport(
                    recipe,
                    expectedGeneration: expectedGeneration,
                    expectedIdentity: expectedIdentity,
                    expectedUserID: expectedUserID,
                    continueQueue: true
                )
                try await self.drainServerQueue(
                    language: job.language,
                    userID: expectedUserID,
                    expectedGeneration: expectedGeneration,
                    expectedIdentity: expectedIdentity
                )
            }
            importTask = (id: importTaskID, task: task)
            try await task.value
        } catch is CancellationError {
            return
        } catch {
            guard scopeIsCurrent(
                generation: expectedGeneration,
                identity: expectedIdentity,
                userID: expectedUserID
            ) else { return }
            presentImportError(error, userID: expectedUserID)
        }
    }

    private func extractThenWait(
        normalized: String,
        language: String,
        userID: UUID,
        expectedGeneration: Int,
        expectedIdentity: String?
    ) async throws -> RecipePublic {
        let started = try await api.extract(url: normalized, language: language)
        let record = PersistedImportJob(
            jobID: started.jobId,
            language: language,
            userID: userID,
            sourceURL: normalized
        )
        ImportJobStore.save(record)
        await MainActor.run {
            guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: userID) else { return }
            statusMessage = Self.localizedImportStatus(started.cacheHit ? "cache hit" : "job \(started.status)")
            importProgress = started.progress ?? 1
        }
        return try await waitForPersistedJob(
            record,
            expectedGeneration: expectedGeneration,
            expectedIdentity: expectedIdentity,
            expectedUserID: userID
        )
    }

    private func waitForPersistedJob(
        _ job: PersistedImportJob,
        expectedGeneration: Int,
        expectedIdentity: String?,
        expectedUserID: UUID
    ) async throws -> RecipePublic {
        try await api.waitForRecipe(jobID: job.jobID, language: job.language) { [weak self] state in
            let nextID = JobFollowPolicy.persistedID(jobID: state.jobId, nextJobID: state.nextJobId)
            ImportJobStore.save(
                PersistedImportJob(
                    jobID: nextID,
                    language: job.language,
                    userID: job.userID,
                    sourceURL: job.sourceURL
                )
            )
            let status = state.status
            let progress = state.progress
            guard let viewModel = self else { return }
            await MainActor.run {
                guard viewModel.scopeIsCurrent(
                    generation: expectedGeneration,
                    identity: expectedIdentity,
                    userID: expectedUserID
                ) else { return }
                viewModel.statusMessage = Self.localizedImportStatus(status)
                viewModel.importProgress = progress ?? viewModel.importProgress
            }
        }
    }

    private func finishImport(
        _ recipe: RecipePublic,
        expectedGeneration: Int,
        expectedIdentity: String?,
        expectedUserID: UUID,
        continueQueue: Bool = false
    ) async throws {
        guard scopeIsCurrent(
            generation: expectedGeneration,
            identity: expectedIdentity,
            userID: expectedUserID
        ) else { throw CancellationError() }
        ImportJobStore.clear(userID: expectedUserID)
        canResumeImport = false
        setCategory(AppViewModel.uncategorized, for: recipe.id)
        lastImportedRecipe = recipe
        cacheRecipeDetail(recipe)
        if !continueQueue {
            selectedRecipe = recipe
            importURL = ""
        }
        statusMessage = String(format: ReciLocalization.string("done: %@"), recipe.title)
        importProgress = 100
        AppLogger.app.info("import completed recipeId=\(recipe.id.uuidString, privacy: .public)")
        await refreshAll(force: true)
    }

    private func presentImportError(_ error: Error, userID: UUID) {
        statusMessage = ""
        importProgress = 0
        AppLogger.app.error("import failed: \(error.localizedDescription, privacy: .public)")

        if isUnauthorized(error) {
            ImportJobStore.clear(userID: userID)
            canResumeImport = false
            Task { await auth?.signOut() }
            errorMessage = ReciLocalization.string("Not signed in")
            return
        }

        let retain: Bool
        if let appError = error as? AppError {
            retain = ImportJobRetentionPolicy.shouldRetainForResume(
                status: Self.statusCode(for: appError),
                code: Self.errorCode(for: appError)
            )
            applyImportAction(appError)
        } else if let urlError = error as? URLError {
            retain = ImportJobRetentionPolicy.shouldRetainURLError(urlError.code)
            if urlError.code == .timedOut {
                errorMessage = ReciLocalization.string("Still working on the server. Resume to check this import again.")
            } else if urlError.code == .notConnectedToInternet {
                errorMessage = ReciLocalization.string("No internet connection. You can resume this import when you're back online.")
            } else {
                errorMessage = error.localizedDescription
            }
        } else if error is CancellationError {
            retain = true
            return
        } else {
            retain = false
            errorMessage = error.localizedDescription
        }

        canResumeImport = retain && ImportJobStore.load(userID: userID) != nil
        if !retain {
            ImportJobStore.clear(userID: userID)
        }
    }

    private func applyImportAction(_ error: AppError) {
        errorMessage = error.localizedDescription
        switch error.apiAction {
        case .presentPaywall:
            SubscriptionService.shared.presentUpgrade { [weak self] in
                Task { @MainActor in
                    await self?.refreshSubscriptionState()
                }
            }
        case .reauthenticate:
            Task { await auth?.signOut() }
        default:
            break
        }
    }

    private static func statusCode(for error: AppError) -> Int {
        switch error {
        case .unauthorized: 401
        case .quota, .fairUse, .forbidden: 403
        case .notFound: 404
        case .invalidInput: 422
        case .rateLimited: 429
        case .unavailable: 503
        case .jobFailed: 200
        case .transient: 503
        case .server, .noRecipe: 500
        }
    }

    private static func errorCode(for error: AppError) -> String? {
        switch error {
        case .quota(let detail): detail.code
        case .fairUse: "PRO_FAIR_USE_LIMIT"
        case .jobFailed: "JOB_FAILED"
        default: nil
        }
    }

    private func isUnauthorized(_ error: Error) -> Bool {
        if let appError = error as? AppError, case .unauthorized = appError { return true }
        return false
    }

    func refreshSubscriptionState() async {
        subscriptionRefreshGeneration += 1
        let subscriptionGeneration = subscriptionRefreshGeneration
        let expectedClientGeneration = generation
        for delay in [UInt64(0), 2, 5, 10] {
            guard !Task.isCancelled,
                  subscriptionGeneration == subscriptionRefreshGeneration,
                  expectedClientGeneration == generation else { return }
            if delay > 0 {
                let jitter = Double.random(in: 0...0.4)
                do { try await Task.sleep(for: .seconds(Double(delay) + jitter)) }
                catch { return }
            }
            guard !Task.isCancelled,
                  subscriptionGeneration == subscriptionRefreshGeneration,
                  expectedClientGeneration == generation,
                  token != nil else { return }
            do {
            let fetchedMe = try await sharedProfile()
                guard !Task.isCancelled,
                      subscriptionGeneration == subscriptionRefreshGeneration,
                      expectedClientGeneration == generation else { return }
                me = fetchedMe
                SubscriptionService.shared.identify(userID: fetchedMe.id)
                if fetchedMe.isPro { return }
            } catch {
                continue
            }
        }
    }

    func fetchRecipe(_ summary: RecipeSummary) async throws -> RecipePublic {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-reciapp-design-preview")
            || summary.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) {
            return RecipePublic(
                id: summary.id,
                title: summary.title,
                ingredients: [
                    Ingredient(name: "rigatoni", quantity: "250", unit: "g"),
                    Ingredient(name: "salted water", quantity: nil, unit: nil),
                    Ingredient(name: "ripe tomatoes", quantity: "4", unit: nil),
                    Ingredient(name: "parmesan", quantity: "60", unit: "g"),
                    Ingredient(name: "fresh basil", quantity: "1", unit: "handful"),
                ],
                ingredientSections: [
                    IngredientSection(
                        title: "Pasta",
                        ingredients: [
                            Ingredient(name: "rigatoni", quantity: "250", unit: "g"),
                            Ingredient(name: "salted water", quantity: nil, unit: nil),
                        ]
                    ),
                    IngredientSection(
                        title: "Tomato sauce",
                        ingredients: [
                            Ingredient(name: "ripe tomatoes", quantity: "4", unit: nil),
                            Ingredient(name: "parmesan", quantity: "60", unit: "g"),
                            Ingredient(name: "fresh basil", quantity: "1", unit: "handful"),
                        ]
                    ),
                ],
                steps: [
                    Step(order: 1, text: "Boil the pasta in salted water until just al dente.", durationMinutes: 10),
                    Step(order: 2, text: "Cook the tomatoes with olive oil until soft and glossy.", durationMinutes: 12),
                    Step(order: 3, text: "Fold in the pasta, parmesan and basil. Serve warm.", durationMinutes: 3),
                ],
                servings: summary.servings,
                prepMinutes: summary.prepMinutes,
                cookMinutes: summary.cookMinutes,
                tags: ["Pasta", "Weeknight"],
                sourceUrl: summary.sourceUrl,
                platform: summary.platform,
                thumbnailUrl: summary.thumbnailUrl,
                carouselImageUrls: [
                    summary.thumbnailUrl,
                    "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?auto=format&fit=crop&w=1200&q=85",
                ].compactMap { $0 },
                author: summary.author,
                description: "A simple, comforting pasta with sweet tomatoes, parmesan and fresh basil. Finish with a little pasta water for a glossy sauce and serve immediately while everything is warm.",
                tips: [
                    RecipeTip(title: "Storage", text: "Keep leftovers in an airtight container in the fridge for up to 3 days."),
                    RecipeTip(title: "To serve", text: "Loosen with a splash of warm pasta water before reheating or serving.")
                ]
            )
        }
        #endif

        let language = AppLanguageStore.current.serverCode
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        guard let expectedUserID = activeUserID else { throw AppError.unauthorized }
        let importedRecipe = lastImportedRecipe.flatMap {
            $0.id == summary.id && $0.languageCode == language ? $0 : nil
        }
        let diskRecipe = recipeDetailsCache[summary.id].flatMap {
            $0.languageCode == language ? $0 : nil
        }
        let cachedRecipe = importedRecipe ?? diskRecipe
        switch detailRevalidationPolicy.decision(
            cached: cachedRecipe,
            recipeID: summary.id,
            scope: ClientScope(userID: expectedUserID, language: language)
        ) {
        case .cached(let cachedRecipe, let shouldRevalidate):
            let source = importedRecipe == nil ? "disk" : "import"
            AppLogger.app.info("recipe detail cache hit source=\(source, privacy: .public) id=\(summary.id.uuidString, privacy: .public)")
            if shouldRevalidate { revalidateCachedDetail(id: summary.id, language: language) }
            return cachedRecipe
        case .fetch:
            break
        }

        guard token != nil else { throw AppError.unauthorized }
        do {
            let recipe = try await sharedDetail(id: summary.id, language: language)
            guard scopeIsCurrent(
                generation: expectedGeneration,
                identity: expectedIdentity,
                userID: expectedUserID
            ) else {
                throw CancellationError()
            }
            cacheRecipeDetail(recipe)
            AppLogger.app.info("recipe loaded id=\(summary.id.uuidString, privacy: .public)")
            return recipe
        } catch {
            AppLogger.app.error("recipe load failed id=\(summary.id.uuidString, privacy: .public): \(error.localizedDescription, privacy: .public)")
            throw error
        }
    }

    private func revalidateCachedDetail(id: UUID, language: String) {
        guard let userID = activeUserID, token != nil else { return }
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        Task { [weak self] in
            guard let self else { return }
            do {
                let refreshed = try await self.sharedDetail(id: id, language: language)
                guard self.scopeIsCurrent(
                    generation: expectedGeneration,
                    identity: expectedIdentity,
                    userID: userID
                ) else { return }
                self.cacheRecipeDetail(refreshed)
                self.refreshedDetail = refreshed
                if self.selectedRecipe?.id == id { self.selectedRecipe = refreshed }
            } catch is CancellationError {
                return
            } catch {
                AppLogger.app.info("cached detail retained after revalidation failure id=\(id.uuidString, privacy: .public)")
            }
        }
    }

    private func sharedLibrary(language: String) async throws -> [RecipeSummary] {
        guard let scope = activeRecipeCacheIdentity else { throw AppError.unauthorized }
        let entry = libraryTasks.acquire(for: scope) {
            Task { try await self.api.myRecipes(language: language) }
        }
        defer { libraryTasks.release(key: scope, id: entry.id) }
        return try await entry.task.value
    }

    private func sharedProfile() async throws -> MeResponse {
        guard let scope = activeRecipeCacheIdentity else { throw AppError.unauthorized }
        let entry = profileTasks.acquire(for: scope) {
            Task { try await self.api.me() }
        }
        defer { profileTasks.release(key: scope, id: entry.id) }
        return try await entry.task.value
    }

    private func sharedDetail(id: UUID, language: String) async throws -> RecipePublic {
        guard let scope = activeRecipeCacheIdentity else { throw AppError.unauthorized }
        let identity = "\(scope).\(id.uuidString).\(language)"
        let entry = detailTasks.acquire(for: identity) {
            Task { try await self.api.recipe(id: id, language: language) }
        }
        defer { detailTasks.release(key: identity, id: entry.id) }
        return try await entry.task.value
    }

    func deleteRecipe(_ summary: RecipeSummary) async {
        #if DEBUG
        if summary.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) {
            recipes.removeAll { $0.id == summary.id }
            recipeCategories.removeValue(forKey: summary.id)
            favoriteIDs.remove(summary.id)
            recipeTags.removeValue(forKey: summary.id)
            if selectedRecipe?.id == summary.id { selectedRecipe = nil }
            saveLocalCategories()
            return
        }
        #endif
        guard token != nil else { return }
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        guard let expectedUserID = activeUserID else { return }
        do {
            _ = try await api.removeRecipe(id: summary.id)
            guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: expectedUserID) else { return }
            if selectedRecipe?.id == summary.id { selectedRecipe = nil }
            recipeDetailsCache.removeValue(forKey: summary.id)
            recipeCategories.removeValue(forKey: summary.id)
            favoriteIDs.remove(summary.id)
            recipeTags.removeValue(forKey: summary.id)
            saveLocalCategories()
            await refreshAll(force: true)
        } catch {
            guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: expectedUserID) else { return }
            if isUnauthorized(error) {
                await auth?.signOut()
            }
            errorMessage = error.localizedDescription
        }
    }

    func deleteAccount() async {
        guard token != nil else { return }
        let expectedGeneration = generation
        let expectedIdentity = activeRecipeCacheIdentity
        guard let expectedUserID = activeUserID else { return }
        do {
            _ = try await api.deleteAccount()
            guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: expectedUserID) else { return }
            sessionDidEnd()
            await auth?.signOut()
        } catch {
            guard scopeIsCurrent(generation: expectedGeneration, identity: expectedIdentity, userID: expectedUserID) else { return }
            if isUnauthorized(error) {
                await auth?.signOut()
            }
            errorMessage = error.localizedDescription
        }
    }

    var allCategoryNames: [String] {
        var names = [Self.uncategorized]
        for category in customCategories where category != Self.uncategorized {
            if !names.contains(category) { names.append(category) }
        }
        for category in recipeCategories.values where category != Self.uncategorized {
            if !names.contains(category) { names.append(category) }
        }
        return names
    }

    func parentCategory(of category: String) -> String? {
        categoryParents[category]
    }

    func childCategoryNames(of parent: String?) -> [String] {
        var folders = FolderHierarchyPolicy.orderedChildren(
            of: parent,
            folders: customCategories,
            parents: categoryParents
        )
        if parent == nil {
            folders.insert(Self.uncategorized, at: 0)
        }
        return folders
    }

    func childFolders(of parent: String?) -> [RecipeCategoryFolder] {
        childCategoryNames(of: parent).map { category in
            RecipeCategoryFolder(
                name: category,
                count: recipes(in: category, includingDescendants: true).count,
                colorHex: colorHex(for: category)
            )
        }
    }

    func updateFolderDisplayPreferences(
        sort: FolderSort? = nil,
        columns: Int? = nil,
        folderLayout: CollectionLayout? = nil,
        recipeLayout: CollectionLayout? = nil,
        recipeColumns: Int? = nil
    ) {
        if let sort { folderSortRawValue = sort.rawValue }
        if let columns { folderColumns = min(max(columns, 1), 3) }
        if let folderLayout { folderLayoutRawValue = folderLayout.rawValue }
        if let recipeLayout { recipeLayoutRawValue = recipeLayout.rawValue }
        if let recipeColumns { self.recipeColumns = min(max(recipeColumns, 1), 3) }
        persistFolderCache()
    }

    func resetFolderDisplayPreferences() {
        folderSortRawValue = FolderSort.created.rawValue
        folderColumns = 2
        folderLayoutRawValue = CollectionLayout.grid.rawValue
        recipeLayoutRawValue = CollectionLayout.grid.rawValue
        recipeColumns = 2
        persistFolderCache()
    }

    func folderPath(_ category: String) -> String {
        guard category != Self.uncategorized else { return Self.localizedCategoryName(category) }
        var parts = [category]
        var current = categoryParents[category]
        var visited = Set([category])
        while let name = current, visited.insert(name).inserted {
            parts.append(name)
            current = categoryParents[name]
        }
        return parts.reversed().joined(separator: " / ")
    }

    func descendantCategoryNames(of category: String) -> Set<String> {
        var result = Set<String>()
        var pending = [category]
        while let parent = pending.popLast() {
            for child in customCategories where categoryParents[child] == parent && result.insert(child).inserted {
                pending.append(child)
            }
        }
        return result
    }

    func category(for recipeId: UUID) -> String {
        recipeCategories[recipeId] ?? Self.uncategorized
    }

    static func localizedCategoryName(_ name: String) -> String {
        name == Self.uncategorized ? ReciLocalization.string("Uncategorized") : name
    }

    func recipes(in category: String) -> [RecipeSummary] {
        groupedRecipesCache[category] ?? []
    }

    func recipes(in category: String, includingDescendants: Bool) -> [RecipeSummary] {
        guard includingDescendants, category != Self.uncategorized else { return recipes(in: category) }
        let folders = descendantCategoryNames(of: category).union([category])
        return folders.flatMap { groupedRecipesCache[$0] ?? [] }
    }

    /// Groups the current summaries once so folder screens do not scan the full list per folder.
    func recipesByCategory() -> [String: [RecipeSummary]] {
        groupedRecipesCache
    }

    func categoryCounts() -> [RecipeCategoryFolder] {
        categoryFoldersCache
    }

    func categoryCounts(using groupedRecipes: [String: [RecipeSummary]]) -> [RecipeCategoryFolder] {
        allCategoryNames
            .map { category in
                let names = category == Self.uncategorized
                    ? Set([category])
                    : descendantCategoryNames(of: category).union([category])
                let count = names.reduce(0) { $0 + (groupedRecipes[$1]?.count ?? 0) }
                return RecipeCategoryFolder(name: category, count: count, colorHex: colorHex(for: category))
            }
            .filter { $0.count > 0 || customCategories.contains($0.name) }
    }

    func colorHex(for category: String) -> String {
        if category == Self.uncategorized { return "D8D2C8" }
        let index = customCategories.firstIndex(of: category) ?? 0
        return categoryColors[category] ?? categoryPalette[index % categoryPalette.count]
    }

    @discardableResult
    func addCategory(_ name: String, colorHex: String? = nil, parent: String? = nil) -> Bool {
        let clean = cleanCategoryName(name)
        organizationErrorMessage = nil
        guard !clean.isEmpty, clean != Self.uncategorized else {
            organizationErrorMessage = ReciLocalization.string("Enter a valid folder name.")
            return false
        }
        guard !FolderHierarchyPolicy.containsDuplicate(clean, folders: customCategories) else {
            organizationErrorMessage = ReciLocalization.string("A folder with this name already exists.")
            return false
        }
        let targetParent = parent == Self.uncategorized ? nil : parent
        guard targetParent == nil || customCategories.contains(targetParent!) else {
            organizationErrorMessage = ReciLocalization.string("The destination folder no longer exists.")
            return false
        }
        customCategories.append(clean)
        if let targetParent { categoryParents[clean] = targetParent }
        categoryColors[clean] = colorHex ?? categoryColors[clean] ?? categoryPalette[(customCategories.count - 1) % categoryPalette.count]
        saveLocalCategories()
        return true
    }

    func createDebugColorFolders() {
        for (index, colorHex) in categoryPalette.enumerated() {
            addCategory("Debug color \(index + 1)", colorHex: colorHex)
        }
    }

    func createDebugMaxLengthFolders() {
        let prefix = "Debug folder "
        for index in 1...3 {
            let suffix = "\(index)"
            let padding = String(
                repeating: "x",
                count: max(0, Self.categoryNameMaxLength - prefix.count - suffix.count)
            )
            addCategory(prefix + padding + suffix)
        }
    }

    func createDebugRecipesPerFolder() {
        let oldDebugIDs = recipes
            .filter { $0.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) }
            .map(\.id)
        recipes.removeAll { $0.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) }
        oldDebugIDs.forEach { recipeCategories.removeValue(forKey: $0) }

        for category in customCategories {
            for index in 1...Int.random(in: 3...9) {
                let recipe = RecipeSummary(
                    id: UUID(),
                    title: "Test recipe \(index) · \(category)",
                    platform: "Debug",
                    sourceUrl: "\(Self.debugRecipeSourcePrefix)\(UUID().uuidString)",
                    thumbnailUrl: nil,
                    author: "ReciApp Debug",
                    servings: 2,
                    prepMinutes: 10,
                    cookMinutes: 15,
                    savedAt: ""
                )
                recipes.append(recipe)
                recipeCategories[recipe.id] = category
            }
        }
        saveLocalCategories()
    }

    func createDebugPerformanceData() {
        let oldDebugIDs = recipes
            .filter { $0.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) }
            .map(\.id)
        recipes.removeAll { $0.sourceUrl.hasPrefix(Self.debugRecipeSourcePrefix) }

        var updatedCategories = recipeCategories
        oldDebugIDs.forEach { updatedCategories.removeValue(forKey: $0) }

        customCategories.removeAll { $0.hasPrefix(Self.debugPerformanceFolderPrefix) }
        categoryColors = categoryColors.filter { !$0.key.hasPrefix(Self.debugPerformanceFolderPrefix) }
        categoryParents = categoryParents.filter {
            !$0.key.hasPrefix(Self.debugPerformanceFolderPrefix)
                && !$0.value.hasPrefix(Self.debugPerformanceFolderPrefix)
        }

        let performanceFolders = (1...12).map {
            "\(Self.debugPerformanceFolderPrefix)\(String(format: "%02d", $0))"
        }
        customCategories.append(contentsOf: performanceFolders)

        var generatedRecipes: [RecipeSummary] = []
        generatedRecipes.reserveCapacity(performanceFolders.count * 150)
        for (folderIndex, category) in performanceFolders.enumerated() {
            categoryColors[category] = categoryPalette[folderIndex % categoryPalette.count]
            let recipeCount = Int.random(in: 100...200)
            for recipeIndex in 1...recipeCount {
                let recipe = RecipeSummary(
                    id: UUID(),
                    title: "Performance recipe \(recipeIndex)",
                    platform: "Debug",
                    sourceUrl: "\(Self.debugRecipeSourcePrefix)\(UUID().uuidString)",
                    thumbnailUrl: nil,
                    author: "ReciApp Debug",
                    servings: 2,
                    prepMinutes: 10,
                    cookMinutes: 15,
                    savedAt: ""
                )
                generatedRecipes.append(recipe)
                updatedCategories[recipe.id] = category
            }
        }

        recipes.append(contentsOf: generatedRecipes)
        recipeCategories = updatedCategories
        saveLocalCategories()
    }

    func deleteAllCustomCategories() {
        recipeCategories = recipeCategories.mapValues { _ in Self.uncategorized }
        customCategories.removeAll()
        categoryColors.removeAll()
        categoryParents.removeAll()
        saveLocalCategories()
    }

    @discardableResult
    func updateCategory(_ oldName: String, name: String, colorHex: String, parent: String? = nil) -> Bool {
        organizationErrorMessage = nil
        guard oldName != Self.uncategorized else { return false }
        let clean = cleanCategoryName(name)
        guard !clean.isEmpty else {
            organizationErrorMessage = ReciLocalization.string("Enter a valid folder name.")
            return false
        }
        let targetParent = parent == Self.uncategorized ? nil : parent
        guard targetParent == nil || customCategories.contains(targetParent!) else {
            organizationErrorMessage = ReciLocalization.string("The destination folder no longer exists.")
            return false
        }
        var updatedCategories = customCategories
        var updatedAssignments = recipeCategories
        var updatedColors = categoryColors
        var updatedParents = categoryParents
        if clean != oldName {
            guard !FolderHierarchyPolicy.containsDuplicate(clean, folders: customCategories, excluding: oldName) else {
                organizationErrorMessage = ReciLocalization.string("A folder with this name already exists.")
                return false
            }
            if let oldIndex = updatedCategories.firstIndex(of: oldName) {
                updatedCategories[oldIndex] = clean
            } else {
                updatedCategories.append(clean)
            }
            updatedAssignments = updatedAssignments.mapValues { $0 == oldName ? clean : $0 }
            if let currentParent = updatedParents.removeValue(forKey: oldName) {
                updatedParents[clean] = currentParent
            }
            updatedParents = updatedParents.mapValues { $0 == oldName ? clean : $0 }
            updatedColors.removeValue(forKey: oldName)
        }
        guard let moved = FolderHierarchyPolicy.moving(clean, to: targetParent, parents: updatedParents) else {
            organizationErrorMessage = ReciLocalization.string("A folder cannot be moved inside itself.")
            return false
        }
        updatedColors[clean] = colorHex
        customCategories = updatedCategories
        recipeCategories = updatedAssignments
        categoryColors = updatedColors
        categoryParents = moved
        saveLocalCategories()
        return true
    }

    func deleteCategory(_ name: String) {
        guard name != Self.uncategorized else { return }
        customCategories.removeAll { $0 == name }
        recipeCategories = recipeCategories.mapValues { $0 == name ? Self.uncategorized : $0 }
        categoryColors.removeValue(forKey: name)
        categoryParents = FolderHierarchyPolicy.promotingChildren(of: name, parents: categoryParents)
        saveLocalCategories()
    }

    func canMoveCategory(_ name: String, to parent: String?) -> Bool {
        guard name != Self.uncategorized else { return false }
        let targetParent = parent == Self.uncategorized ? nil : parent
        guard targetParent == nil || customCategories.contains(targetParent!) else { return false }
        return FolderHierarchyPolicy.canMove(name, to: targetParent, parents: categoryParents)
    }

    @discardableResult
    func moveCategory(_ name: String, to parent: String?) -> Bool {
        organizationErrorMessage = nil
        let targetParent = parent == Self.uncategorized ? nil : parent
        guard canMoveCategory(name, to: targetParent),
              let moved = FolderHierarchyPolicy.moving(name, to: targetParent, parents: categoryParents) else {
            organizationErrorMessage = ReciLocalization.string("A folder cannot be moved inside itself.")
            return false
        }
        categoryParents = moved
        saveLocalCategories()
        return true
    }

    func setCategory(_ name: String, for recipeId: UUID) {
        let clean = cleanCategoryName(name)
        let category = clean.isEmpty ? Self.uncategorized : clean
        if category != Self.uncategorized, !customCategories.contains(category) {
            _ = addCategory(category)
        }
        recipeCategories[recipeId] = category
        saveLocalCategories()
    }

    func isFavorite(_ recipeID: UUID) -> Bool {
        favoriteIDs.contains(recipeID)
    }

    func toggleFavorite(_ recipeID: UUID) {
        if favoriteIDs.contains(recipeID) {
            favoriteIDs.remove(recipeID)
        } else {
            favoriteIDs.insert(recipeID)
        }
        saveLocalCategories()
    }

    func tags(for recipeID: UUID) -> [String] {
        recipeTags[recipeID] ?? []
    }

    func addTag(_ raw: String, to recipeID: UUID) {
        let next = RecipeAnnotationPolicy.adding(raw, to: tags(for: recipeID))
        if next.isEmpty {
            recipeTags.removeValue(forKey: recipeID)
        } else {
            recipeTags[recipeID] = next
        }
        saveLocalCategories()
    }

    func removeTag(_ tag: String, from recipeID: UUID) {
        let next = RecipeAnnotationPolicy.removing(tag, from: tags(for: recipeID))
        if next.isEmpty {
            recipeTags.removeValue(forKey: recipeID)
        } else {
            recipeTags[recipeID] = next
        }
        saveLocalCategories()
    }

    func moveRecipes(withIDs recipeIDs: Set<UUID>, to name: String) {
        let clean = cleanCategoryName(name)
        let category = clean.isEmpty ? Self.uncategorized : clean

        if category != Self.uncategorized, !customCategories.contains(category) {
            customCategories.append(category)
            if categoryColors[category] == nil {
                categoryColors[category] = categoryPalette[(customCategories.count - 1) % categoryPalette.count]
            }
        }

        for recipeID in recipeIDs {
            recipeCategories[recipeID] = category
        }
        saveLocalCategories()
    }

    /// Moves many recipes while publishing and persisting the mapping only once.

    private func saveLocalCategories() {
        rebuildFolderCache()
        persistFolderCache()
        persistRecipeCache()
    }

    func activate(userID: UUID, language: String) {
        let identity = ClientScope(userID: userID, language: language).identity
        guard identity != activeRecipeCacheIdentity else { return }

        generation += 1
        cancelPendingWork()
        activeUserID = userID
        activeRecipeCacheIdentity = identity
        recipes = []
        recipeDetailsCache = [:]
        recipeCategories = [:]
        customCategories = []
        categoryColors = [:]
        categoryParents = [:]
        folderSortRawValue = FolderSort.created.rawValue
        folderColumns = 2
        folderLayoutRawValue = CollectionLayout.grid.rawValue
        recipeLayoutRawValue = CollectionLayout.grid.rawValue
        recipeColumns = 2
        favoriteIDs = []
        recipeTags = [:]
        selectedRecipe = nil
        selectedRecipeSummary = nil
        lastImportedRecipe = nil
        me = nil
        isLoading = false
        isImporting = false
        canResumeImport = ImportJobStore.load(userID: userID) != nil
        statusMessage = canResumeImport ? ReciLocalization.string("An import is still in progress.") : ""
        importProgress = 0
        consumedShareIDs.removeAll()
        lastServerQueue = []
        detailRevalidationPolicy.reset()

        loadFolderCache(userID: userID)

        guard let data = UserDefaults.standard.data(forKey: recipeCacheKey(for: identity)) else {
            rebuildFolderCache()
            AppLogger.app.info("recipe cache miss identity=\(identity, privacy: .private(mask: .hash))")
            return
        }

        do {
            let snapshot = try JSONDecoder().decode(RecipeCacheSnapshot.self, from: data)
            recipes = snapshot.recipes
            recipeDetailsCache = Dictionary(
                snapshot.recipeDetails.map { ($0.id, $0) },
                uniquingKeysWith: { _, newest in newest }
            )
            reconcileLocalRecipeIds(pruneMissing: false)
            rebuildFolderCache()
            AppLogger.app.info("recipe cache hit recipes=\(self.recipes.count, privacy: .public) details=\(self.recipeDetailsCache.count, privacy: .public)")
        } catch {
            UserDefaults.standard.removeObject(forKey: recipeCacheKey(for: identity))
            recipes = []
            rebuildFolderCache()
            AppLogger.app.error("recipe cache decode failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    func sessionDidEnd() {
        guard activeUserID != nil || activeRecipeCacheIdentity != nil else { return }
        let departingUser = activeUserID
        generation += 1
        cancelPendingWork()
        if let departingUser {
            let prefix = "\(recipeCacheKeyPrefix).\(departingUser.uuidString)."
            for key in UserDefaults.standard.dictionaryRepresentation().keys where key.hasPrefix(prefix) {
                UserDefaults.standard.removeObject(forKey: key)
            }
            UserDefaults.standard.removeObject(forKey: folderCacheKey(for: departingUser))
            ImportJobStore.clear(userID: departingUser)
        }
        activeUserID = nil
        activeRecipeCacheIdentity = nil
        recipes = []
        recipeDetailsCache = [:]
        recipeCategories = [:]
        customCategories = []
        categoryColors = [:]
        categoryParents = [:]
        folderSortRawValue = FolderSort.created.rawValue
        folderColumns = 2
        folderLayoutRawValue = CollectionLayout.grid.rawValue
        recipeLayoutRawValue = CollectionLayout.grid.rawValue
        recipeColumns = 2
        favoriteIDs = []
        recipeTags = [:]
        selectedRecipe = nil
        selectedRecipeSummary = nil
        lastImportedRecipe = nil
        me = nil
        isLoading = false
        isImporting = false
        canResumeImport = false
        statusMessage = ""
        importProgress = 0
        consumedShareIDs.removeAll()
        lastServerQueue = []
        rebuildFolderCache()
    }

    private func persistRecipeCache() {
        guard let identity = activeRecipeCacheIdentity else { return }
        let snapshot = RecipeCacheSnapshot(
            recipes: recipes,
            recipeDetails: Array(recipeDetailsCache.values),
            savedAt: Date()
        )
        do {
            UserDefaults.standard.set(try JSONEncoder().encode(snapshot), forKey: recipeCacheKey(for: identity))
            AppLogger.app.debug("recipe cache saved recipes=\(self.recipes.count, privacy: .public) folders=\(self.categoryFoldersCache.count, privacy: .public)")
        } catch {
            AppLogger.app.error("recipe cache encode failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func cacheRecipeDetail(_ recipe: RecipePublic) {
        recipeDetailsCache[recipe.id] = recipe
        persistRecipeCache()
    }

    private func recipeCacheKey(for identity: String) -> String {
        "\(recipeCacheKeyPrefix).\(identity)"
    }

    private func folderCacheKey(for userID: UUID) -> String {
        ClientScope(userID: userID, language: "").folderCacheKey
    }

    private func persistFolderCache() {
        guard let activeUserID else { return }
        let rawCategories = recipeCategories.reduce(into: [String: String]()) { result, item in
            result[item.key.uuidString] = item.value
        }
        let snapshot = FolderCacheSnapshot(
            recipeCategories: rawCategories,
            customCategories: customCategories,
            categoryColors: categoryColors,
            categoryParents: categoryParents,
            favoriteIDs: favoriteIDs.map(\.uuidString),
            recipeTags: recipeTags.reduce(into: [:]) { result, item in
                result[item.key.uuidString] = item.value
            },
            folderSortRawValue: folderSortRawValue,
            folderColumns: folderColumns,
            folderLayoutRawValue: folderLayoutRawValue,
            recipeLayoutRawValue: recipeLayoutRawValue,
            recipeColumns: recipeColumns
        )
        if let data = try? JSONEncoder().encode(snapshot) {
            UserDefaults.standard.set(data, forKey: folderCacheKey(for: activeUserID))
        }
    }

    private func loadFolderCache(userID: UUID) {
        guard let data = UserDefaults.standard.data(forKey: folderCacheKey(for: userID)),
              let snapshot = try? JSONDecoder().decode(FolderCacheSnapshot.self, from: data) else { return }
        customCategories = snapshot.customCategories
        categoryColors = snapshot.categoryColors
        categoryParents = FolderHierarchyPolicy.sanitizedParents(
            folders: customCategories,
            parents: snapshot.categoryParents ?? [:]
        )
        let validCategories = Set(customCategories).union([Self.uncategorized])
        recipeCategories = snapshot.recipeCategories.reduce(into: [:]) { result, item in
            guard let id = UUID(uuidString: item.key) else { return }
            result[id] = validCategories.contains(item.value) ? item.value : Self.uncategorized
        }
        favoriteIDs = Set(snapshot.favoriteIDs.compactMap(UUID.init(uuidString:)))
        recipeTags = snapshot.recipeTags.reduce(into: [:]) { result, item in
            guard let id = UUID(uuidString: item.key) else { return }
            result[id] = item.value
        }
        folderSortRawValue = FolderSort(rawValue: snapshot.folderSortRawValue ?? "")?.rawValue ?? FolderSort.created.rawValue
        folderColumns = min(max(snapshot.folderColumns ?? 2, 1), 3)
        folderLayoutRawValue = CollectionLayout(rawValue: snapshot.folderLayoutRawValue ?? "")?.rawValue ?? CollectionLayout.grid.rawValue
        recipeLayoutRawValue = CollectionLayout(rawValue: snapshot.recipeLayoutRawValue ?? "")?.rawValue ?? CollectionLayout.grid.rawValue
        recipeColumns = min(max(snapshot.recipeColumns ?? 2, 1), 3)
    }

    private func removeLegacyCachesOnce() {
        let defaults = UserDefaults.standard
        guard !defaults.bool(forKey: migrationKey) else { return }
        for key in CacheMigrationPolicy.keysToRemove(from: defaults.dictionaryRepresentation().keys) {
            defaults.removeObject(forKey: key)
        }
        defaults.set(true, forKey: migrationKey)
    }

    private func cancelPendingWork() {
        libraryTasks.cancelAll()
        profileTasks.cancelAll()
        detailTasks.cancelAll()
        importTask?.task.cancel()
        importTask = nil
        subscriptionRefreshGeneration += 1
    }

    private func rebuildFolderCache() {
        let grouped = recipes.reduce(into: [String: [RecipeSummary]]()) { result, recipe in
            result[category(for: recipe.id), default: []].append(recipe)
        }
        groupedRecipesCache = grouped
        categoryFoldersCache = categoryCounts(using: grouped)
        AppLogger.app.debug("folder cache rebuilt recipes=\(self.recipes.count, privacy: .public) folders=\(self.categoryFoldersCache.count, privacy: .public)")
    }

    private func reconcileLocalRecipeIds(pruneMissing: Bool) {
        let liveIds = Set(recipes.map(\.id))
        let reconciled = FolderAssignmentPolicy.reconciled(
            liveRecipeIDs: liveIds,
            assignments: recipeCategories,
            customFolders: customCategories,
            uncategorized: Self.uncategorized,
            pruneMissing: pruneMissing
        )
        let annotations = RecipeAnnotationPolicy.pruned(
            liveRecipeIDs: liveIds,
            favorites: favoriteIDs,
            tags: recipeTags,
            pruneMissing: pruneMissing
        )
        let assignmentsChanged = reconciled != recipeCategories
        let annotationsChanged = annotations.favorites != favoriteIDs || annotations.tags != recipeTags
        if assignmentsChanged {
            recipeCategories = reconciled
        }
        if annotationsChanged {
            favoriteIDs = annotations.favorites
            recipeTags = annotations.tags
        }
        if assignmentsChanged || annotationsChanged {
            saveLocalCategories()
        }
    }

    private static func localizedImportStatus(_ status: String) -> String {
        if status == "cache hit" {
            return ReciLocalization.string("cache hit")
        }
        if status.hasPrefix("job ") {
            let state = String(status.dropFirst(4))
            return String(format: ReciLocalization.string("job %@"), localizedJobState(state))
        }
        if status.hasPrefix("poll "), let separator = status.firstIndex(of: ":") {
            let stateStart = status.index(after: separator)
            let state = String(status[stateStart...]).trimmingCharacters(in: .whitespaces)
            return localizedJobState(state)
        }
        if ["pending", "processing", "completed", "failed"].contains(status) {
            return localizedJobState(status)
        }
        return status
    }

    private func scopeIsCurrent(generation expectedGeneration: Int, identity: String?, userID: UUID) -> Bool {
        ScopeGuardPolicy.accepts(
            expectedGeneration: expectedGeneration,
            expectedIdentity: identity,
            currentGeneration: generation,
            currentIdentity: activeRecipeCacheIdentity
        ) && activeUserID == userID && auth?.session?.user.id == userID
    }

    private static func localizedJobState(_ state: String) -> String {
        ReciLocalization.string(state, fallback: state)
    }

    private func cleanCategoryName(_ name: String) -> String {
        String(
            name.trimmingCharacters(in: .whitespacesAndNewlines)
                .prefix(Self.categoryNameMaxLength)
        )
    }
}

private func capture<T>(_ operation: @escaping () async throws -> T) async -> Result<T, Error> {
    do { return .success(try await operation()) }
    catch { return .failure(error) }
}

#if os(iOS)
import UIKit
#endif
