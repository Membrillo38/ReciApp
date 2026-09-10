import Foundation
import Testing
@testable import ClientStateHarness

final class LockedRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String] = []

    func append(_ value: String) {
        lock.lock()
        storage.append(value)
        lock.unlock()
    }

    var values: [String] {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}

@Test func cacheScopeIsolatesAccountsAndLanguagesButSharesFoldersPerAccount() {
    let first = UUID()
    let second = UUID()
    let english = ClientScope(userID: first, language: "en-US")
    let spanish = ClientScope(userID: first, language: "es-ES")
    let canonicalSpanish = ClientScope(userID: first, language: "es_MX")
    let other = ClientScope(userID: second, language: "en-US")

    #expect(english.recipeCacheKey != spanish.recipeCacheKey)
    #expect(spanish.recipeCacheKey == canonicalSpanish.recipeCacheKey)
    #expect(english.recipeCacheKey != other.recipeCacheKey)
    #expect(english.folderCacheKey == spanish.folderCacheKey)
    #expect(english.folderCacheKey != other.folderCacheKey)
}

@Test func legacyCleanupTargetsOnlyKnownV1AndV2Keys() {
    let keys = [
        "reciapp.recipeCategories.v1",
        "reciapp.customCategories.v1",
        "reciapp.categoryColors.v1",
        "reciapp.recipeCache.v1.user",
        "reciapp.recipeCache.v2.user.en-US",
        "reciapp.recipeCategories.v2",
        "reciapp.folderCache.v2.user",
        "reciapp.recipeCache.v3.user.en-US",
        "unrelated",
    ]
    let removed = CacheMigrationPolicy.keysToRemove(from: keys)
    #expect(removed.count == 7)
    #expect(!removed.contains("reciapp.recipeCache.v3.user.en-US"))
    #expect(!removed.contains("unrelated"))
}

@Test func unknownAndMissingAssignmentsBecomeUncategorized() {
    let kept = UUID()
    let unknown = UUID()
    let missing = UUID()
    let deleted = UUID()
    let reconciled = FolderAssignmentPolicy.reconciled(
        liveRecipeIDs: [kept, unknown, missing],
        assignments: [kept: "Dinner", unknown: "Other account folder", deleted: "Dinner"],
        customFolders: ["Dinner"],
        uncategorized: "Uncategorized"
    )
    #expect(reconciled == [kept: "Dinner", unknown: "Uncategorized", missing: "Uncategorized"])
}

@Test func folderHierarchyRejectsSelfParentAndCycles() {
    let parents = ["Dinner": "Plans", "Plans": "Archive"]

    #expect(!FolderHierarchyPolicy.canMove("Dinner", to: "Dinner", parents: parents))
    #expect(!FolderHierarchyPolicy.canMove("Archive", to: "Dinner", parents: parents))
    #expect(FolderHierarchyPolicy.canMove("Dinner", to: "Archive", parents: parents))
    #expect(FolderHierarchyPolicy.moving("Archive", to: "Dinner", parents: parents) == nil)
}

@Test func folderHierarchyPromotesChildrenWhenParentIsDeleted() {
    let parents = ["Dinner": "Plans", "Plans": "Archive", "Dessert": "Plans"]
    let promoted = FolderHierarchyPolicy.promotingChildren(of: "Plans", parents: parents)

    #expect(promoted["Dinner"] == "Archive")
    #expect(promoted["Dessert"] == "Archive")
    #expect(promoted["Plans"] == nil)
}

@Test func flatFolderMigrationKeepsEveryFolderAtRoot() {
    let sanitized = FolderHierarchyPolicy.sanitizedParents(
        folders: ["Dinner", "Dessert"],
        parents: [:]
    )

    #expect(sanitized.isEmpty)
    #expect(FolderHierarchyPolicy.orderedChildren(of: nil, folders: ["Dinner", "Dessert"], parents: sanitized) == ["Dinner", "Dessert"])
}

@Test func invalidPersistedHierarchyDropsMissingParentsAndBreaksCyclesWithoutDroppingFolders() {
    let sanitized = FolderHierarchyPolicy.sanitizedParents(
        folders: ["A", "B", "C"],
        parents: ["A": "B", "B": "A", "C": "Missing"]
    )

    #expect(sanitized["C"] == nil)
    #expect(FolderHierarchyPolicy.canMove("A", to: "B", parents: sanitized))
    #expect(FolderHierarchyPolicy.canMove("B", to: nil, parents: sanitized))
    #expect(Set(FolderHierarchyPolicy.orderedChildren(of: nil, folders: ["A", "B", "C"], parents: sanitized)) == ["B", "C"])
}

@Test func languageCacheActivationPreservesOtherLanguageFolderAssignmentsUntilRemoteTruth() {
    let englishRecipe = UUID()
    let spanishRecipe = UUID()
    let assignments = [englishRecipe: "Dinner", spanishRecipe: "Dessert"]
    let cachedLanguage = FolderAssignmentPolicy.reconciled(
        liveRecipeIDs: [englishRecipe],
        assignments: assignments,
        customFolders: ["Dinner", "Dessert"],
        uncategorized: "Uncategorized",
        pruneMissing: false
    )
    #expect(cachedLanguage == assignments)

    let authoritativeRemote = FolderAssignmentPolicy.reconciled(
        liveRecipeIDs: [englishRecipe],
        assignments: assignments,
        customFolders: ["Dinner", "Dessert"],
        uncategorized: "Uncategorized",
        pruneMissing: true
    )
    #expect(authoritativeRemote == [englishRecipe: "Dinner"])
}

@Test func validEmptyLibraryReplacesCacheButMissingOrMalformedResponsePreservesIt() {
    #expect(CacheRefreshPolicy.library(cached: [1, 2], successfulResponse: []) == [])
    #expect(CacheRefreshPolicy.library(cached: [1, 2], successfulResponse: nil) == [1, 2])
}

@Test func accountAndLanguageSwitchRejectOldGeneration() {
    let user = UUID()
    var state = ClientStatePolicy()
    let english = ClientScope(userID: user, language: "en-US")
    let spanish = ClientScope(userID: user, language: "es-ES")
    let activatedEnglish = state.activate(english)
    #expect(activatedEnglish)
    let oldGeneration = state.generation
    #expect(state.accepts(generation: oldGeneration, scope: english))
    let activatedSpanish = state.activate(spanish)
    #expect(activatedSpanish)
    #expect(!state.accepts(generation: oldGeneration, scope: english))
    state.invalidate()
    #expect(!state.accepts(generation: state.generation - 1, scope: spanish))
}

@Test func cancelledImportCannotApplyProgressOrErrorToNewScope() {
    #expect(ScopeGuardPolicy.accepts(
        expectedGeneration: 4,
        expectedIdentity: "user-a.en-US",
        currentGeneration: 4,
        currentIdentity: "user-a.en-US"
    ))
    #expect(!ScopeGuardPolicy.accepts(
        expectedGeneration: 4,
        expectedIdentity: "user-a.en-US",
        currentGeneration: 5,
        currentIdentity: "user-b.en-US"
    ))
}

@Test func accountSwitchDuringUnauthorizedRecoveryCannotUseOtherUsersToken() {
    let userA = UUID()
    let userB = UUID()
    #expect(AuthRecoveryScopePolicy.canUseToken(
        expectedUserID: userA,
        expectedGeneration: 7,
        currentUserID: userA,
        currentGeneration: 7
    ))
    #expect(!AuthRecoveryScopePolicy.canUseToken(
        expectedUserID: userA,
        expectedGeneration: 7,
        currentUserID: userB,
        currentGeneration: 8
    ))
    #expect(!AuthRecoveryScopePolicy.canUseToken(
        expectedUserID: userA,
        expectedGeneration: 7,
        currentUserID: userA,
        currentGeneration: 8
    ))
}

@Test func foregroundRefreshHasThirtySecondCooldownAndForceCanBypassCallerGate() {
    var state = ClientStatePolicy()
    let start = Date(timeIntervalSince1970: 1_000)
    let initial = state.shouldRefreshForeground(at: start)
    let suppressed = state.shouldRefreshForeground(at: start.addingTimeInterval(29.9))
    let elapsed = state.shouldRefreshForeground(at: start.addingTimeInterval(30))
    #expect(initial)
    #expect(!suppressed)
    #expect(elapsed)
}

@Test func ingredientSectionsKeepTitlesOrderAndFlatFallbackWithoutLoss() {
    let flour = Ingredient(name: "Flour", quantity: "200", unit: "g")
    let water = Ingredient(name: "Water", quantity: "120", unit: "ml")
    let salt = Ingredient(name: "Salt", quantity: "1", unit: "tsp")
    let sections = [
        IngredientSection(title: "Dough", ingredients: [flour, water]),
        IngredientSection(title: "Finish", ingredients: [salt]),
    ]
    let displayed = IngredientSectionPolicy.displayed(flat: [flour, water, salt], sections: sections)
    #expect(displayed.map(\.title) == ["Dough", "Finish"])
    #expect(IngredientSectionPolicy.flattened(flat: [], sections: displayed) == [flour, water, salt])

    let fallback = IngredientSectionPolicy.displayed(flat: [flour, water], sections: [])
    #expect(fallback.count == 1)
    #expect(fallback[0].ingredients == [flour, water])
}

@Test @MainActor func sharedWorkUsesOneProductionTaskPerKey() async {
    var coordinator = SharedTaskCoordinator<String, Int, Never>()
    var starts = 0
    let first = coordinator.acquire(for: "library:user-a:en-US") {
        starts += 1
        return Task {
            try? await Task.sleep(for: .milliseconds(30))
            return 42
        }
    }
    let second = coordinator.acquire(for: "library:user-a:en-US") {
        starts += 1
        return Task { 99 }
    }

    #expect(first.id == second.id)
    #expect(starts == 1)
    async let firstValue = first.task.value
    async let secondValue = second.task.value
    #expect(await (firstValue, secondValue) == (42, 42))
    coordinator.release(key: "library:user-a:en-US", id: first.id)
    #expect(coordinator.count == 0)
}

@Test func cachedDetailReturnsImmediatelyAndRevalidatesOncePerRecipeAndLanguage() {
    let recipe = UUID()
    let user = UUID()
    let english = ClientScope(userID: user, language: "en-US")
    let spanish = ClientScope(userID: user, language: "es-ES")
    var policy = DetailRevalidationPolicy()
    if case .cached(let value, let shouldRevalidate) = policy.decision(
        cached: "cached value",
        recipeID: recipe,
        scope: english
    ) {
        #expect(value == "cached value")
        #expect(shouldRevalidate)
    } else {
        Issue.record("expected cached-first decision")
    }
    if case .cached(let value, let shouldRevalidate) = policy.decision(
        cached: "cached value",
        recipeID: recipe,
        scope: english
    ) {
        #expect(value == "cached value")
        #expect(!shouldRevalidate)
    } else {
        Issue.record("expected cached-first decision")
    }
    if case .cached(_, let shouldRevalidate) = policy.decision(
        cached: "traducción",
        recipeID: recipe,
        scope: spanish
    ) {
        #expect(shouldRevalidate)
    } else {
        Issue.record("expected language-specific cached decision")
    }
    if case .fetch = policy.decision(cached: Optional<String>.none, recipeID: recipe, scope: english) {
        // Expected: no cached value means caller must await the remote detail.
    } else {
        Issue.record("expected fetch decision without cache")
    }
}

@Test @MainActor func rejectedTokenCoalescesOnlyWithinOriginalUserAndGeneration() async {
    let userA = UUID()
    let userB = UUID()
    let original = AuthRefreshKey(rejectedToken: "old-jwt", userID: userA, generation: 7)
    let otherUser = AuthRefreshKey(rejectedToken: "old-jwt", userID: userB, generation: 8)
    let newerGeneration = AuthRefreshKey(rejectedToken: "old-jwt", userID: userA, generation: 8)
    var coordinator = SharedTaskCoordinator<AuthRefreshKey, String, Never>()
    var starts = 0

    let first = coordinator.acquire(for: original) {
        starts += 1
        return Task { "token-a-refreshed" }
    }
    let duplicate = coordinator.acquire(for: original) {
        starts += 1
        return Task { "wrong-duplicate" }
    }
    let switchedUser = coordinator.acquire(for: otherUser) {
        starts += 1
        return Task { "token-b" }
    }
    let switchedGeneration = coordinator.acquire(for: newerGeneration) {
        starts += 1
        return Task { "token-a-new-session" }
    }

    #expect(first.id == duplicate.id)
    #expect(first.id != switchedUser.id)
    #expect(first.id != switchedGeneration.id)
    #expect(starts == 3)
    #expect(await duplicate.task.value == "token-a-refreshed")
}

@Test func rejectedTokenRemainsConsumedAcrossSessionInvalidation() {
    var policy = UnauthorizedTokenPolicy()
    #expect(policy.canStartRefresh(for: "old-jwt"))
    policy.finishRefresh(for: "old-jwt")
    #expect(!policy.canStartRefresh(for: "old-jwt"))
    #expect(policy.canStartRefresh(for: "new-jwt"))
    #expect(!policy.canStartRefresh(for: "old-jwt"))
}

@Test func offlineRestoreRetainsExistingSessionAndLogoutClearsBeforeRemoteWait() async {
    #expect(SessionRestorePolicy.preservesLocalSession(hasExistingSession: true, missingSessionError: false))
    #expect(!SessionRestorePolicy.preservesLocalSession(hasExistingSession: false, missingSessionError: false))
    #expect(!SessionRestorePolicy.preservesLocalSession(hasExistingSession: true, missingSessionError: true))

    let recorder = LockedRecorder()
    await LogoutOrderingPolicy.clearBeforeRemote(
        clear: { recorder.append("clear") },
        remote: {
            await Task.yield()
            recorder.append("remote")
        }
    )
    #expect(recorder.values == ["clear", "remote"])
}

@Test func retryPolicyNeverReplaysMutationsAfterTransientResponse() {
    #expect(RequestRetryPolicy.maximumAttempts(method: "GET") == 3)
    #expect(RequestRetryPolicy.maximumAttempts(method: "HEAD") == 3)
    #expect(RequestRetryPolicy.maximumAttempts(method: "POST") == 1)
    #expect(RequestRetryPolicy.maximumAttempts(method: "DELETE") == 1)
    #expect(RequestRetryPolicy.maximumAttempts(method: "PATCH") == 1)
}

@Test func errorBehaviorMapsQuotaFairUseAndOtherForbiddenSeparately() {
    #expect(APIErrorBehavior.action(status: 401, code: nil) == .reauthenticate)
    #expect(APIErrorBehavior.action(status: 403, code: "FREE_WEEKLY_LIMIT") == .presentPaywall)
    #expect(APIErrorBehavior.action(status: 403, code: "PRO_FAIR_USE_LIMIT") == .showFairUse)
    #expect(APIErrorBehavior.action(status: 403, code: "NOPE") == .showForbidden)
    #expect(APIErrorBehavior.action(status: 404, code: nil) == .showNotFound)
    #expect(APIErrorBehavior.action(status: 413, code: nil) == .correctInput)
    #expect(APIErrorBehavior.action(status: 422, code: nil) == .correctInput)
    #expect(APIErrorBehavior.action(status: 429, code: nil) == .waitAndRetry)
    #expect(APIErrorBehavior.action(status: 503, code: nil) == .keepDataAndRetry)
    #expect(APIErrorBehavior.action(status: 200, code: "JOB_FAILED") == .showJobFailure)
}

@Test func errorDetailParserAcceptsStringObjectAndValidationList() {
    let stringData = Data(#"{"detail":"Nope"}"#.utf8)
    #expect(APIErrorDetailParser.parse(data: stringData, status: 400) == .init(code: nil, message: "Nope"))

    let objectData = Data(#"{"detail":{"code":"FREE_WEEKLY_LIMIT","message":"Upgrade"}}"#.utf8)
    #expect(
        APIErrorDetailParser.parse(data: objectData, status: 403)
            == .init(code: "FREE_WEEKLY_LIMIT", message: "Upgrade")
    )

    let listData = Data(#"{"detail":[{"loc":["body","url"],"msg":"Field required"}]}"#.utf8)
    #expect(APIErrorDetailParser.parse(data: listData, status: 422).message == "Field required")
}

@Test func jobFollowUsesNextJobIdAndChecksStatusBeforeRecipe() {
    let job = UUID()
    let next = UUID()
    #expect(JobFollowPolicy.persistedID(jobID: job, nextJobID: next) == next)
    #expect(JobFollowPolicy.persistedID(jobID: job, nextJobID: nil) == job)
    #expect(JobFollowPolicy.outcome(status: "failed", hasRecipe: true) == .failed)
    #expect(JobFollowPolicy.outcome(status: "completed", hasRecipe: true) == .succeeded)
    #expect(JobFollowPolicy.outcome(status: "completed", hasRecipe: false) == .wait)
    #expect(JobFollowPolicy.outcome(status: "processing", hasRecipe: false) == .wait)
}

@Test func importJobRetentionKeepsTransientAndDropsFailedOrInvalid() {
    #expect(ImportJobRetentionPolicy.shouldRetainForResume(status: 429, code: nil))
    #expect(ImportJobRetentionPolicy.shouldRetainForResume(status: 503, code: nil))
    #expect(!ImportJobRetentionPolicy.shouldRetainForResume(status: 403, code: "FREE_WEEKLY_LIMIT"))
    #expect(!ImportJobRetentionPolicy.shouldRetainForResume(status: 200, code: "JOB_FAILED"))
    #expect(!ImportJobRetentionPolicy.shouldRetainForResume(status: 422, code: nil))
    #expect(ImportJobRetentionPolicy.shouldRetainURLError(.timedOut))
    #expect(ImportJobRetentionPolicy.shouldRetainURLError(.notConnectedToInternet))
}

@Test func shareInboxDeduplicatesTheSameURLInsideTheWindow() {
    let now = Date(timeIntervalSince1970: 1_000)
    let first = ShareInboxPolicy.enqueue(url: "https://tiktok.com/x", language: "es-ES", now: now, inbox: [])
    #expect(!first.isDuplicate)
    let duplicate = ShareInboxPolicy.enqueue(
        url: "https://tiktok.com/x",
        language: "es-ES",
        now: now.addingTimeInterval(2),
        inbox: first.inbox
    )
    #expect(duplicate.isDuplicate)
    #expect(duplicate.delivery.id == first.delivery.id)
    let later = ShareInboxPolicy.enqueue(
        url: "https://tiktok.com/x",
        language: "es-ES",
        now: now.addingTimeInterval(4),
        inbox: first.inbox
    )
    #expect(!later.isDuplicate)
    #expect(later.delivery.id != first.delivery.id)
}

@Test func urlNormalizeAllExtractsMultipleSupportedLinksInOrder() {
    let hosts = [
        "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
        "youtube.com", "youtu.be", "m.youtube.com",
        "instagram.com", "www.instagram.com",
        "facebook.com", "fb.watch", "m.facebook.com",
    ]
    let raw = """
    mira https://www.tiktok.com/@a/video/1 y también https://youtu.be/abc123
    junk https://example.com/nope https://www.instagram.com/reel/xyz/
    """
    let urls = URLNormalizePolicy.normalizeAll(raw, supportedHosts: hosts)
    #expect(urls.count == 3)
    #expect(urls[0].contains("tiktok.com"))
    #expect(urls[1].contains("youtu.be"))
    #expect(urls[2].contains("instagram.com"))
}

@Test func shareInboxCapsAtTwentyPending() {
    var inbox: [ShareDelivery] = []
    let now = Date(timeIntervalSince1970: 2_000)
    for index in 0..<25 {
        let result = ShareInboxPolicy.enqueue(
            url: "https://youtu.be/\(index)",
            language: "en-US",
            now: now.addingTimeInterval(Double(index)),
            inbox: inbox
        )
        inbox = result.inbox
    }
    #expect(inbox.count == ShareInboxPolicy.maxPending)
    #expect(inbox.first?.url == "https://youtu.be/5")
    #expect(inbox.last?.url == "https://youtu.be/24")
}

@Test func recipeAnnotationPolicyCleansAndCapsTags() {
    let first = RecipeAnnotationPolicy.adding("  Pasta  ", to: [])
    #expect(first == ["Pasta"])
    #expect(RecipeAnnotationPolicy.adding("pasta", to: first) == first)
    #expect(RecipeAnnotationPolicy.adding("   ", to: first) == first)
    #expect(RecipeAnnotationPolicy.cleanedTag(String(repeating: "a", count: 24))?.count == RecipeAnnotationPolicy.tagMaxLength)

    var tags = (1...RecipeAnnotationPolicy.tagMaxCount).map { "tag \($0)" }
    #expect(RecipeAnnotationPolicy.adding("extra", to: tags) == tags)
    tags = RecipeAnnotationPolicy.removing("Tag 2", from: tags)
    #expect(!tags.contains("tag 2"))
}

@Test func recipeAnnotationPolicyPrunesMissingRecipes() {
    let keep = UUID()
    let gone = UUID()
    let pruned = RecipeAnnotationPolicy.pruned(
        liveRecipeIDs: [keep],
        favorites: [keep, gone],
        tags: [keep: ["Dinner"], gone: ["Old"]],
        pruneMissing: true
    )
    #expect(pruned.favorites == [keep])
    #expect(pruned.tags == [keep: ["Dinner"]])

    let preserved = RecipeAnnotationPolicy.pruned(
        liveRecipeIDs: [keep],
        favorites: [gone],
        tags: [gone: ["Old"]],
        pruneMissing: false
    )
    #expect(preserved.favorites == [gone])
}

@Test func retryAfterDelayIsCapped() {
    #expect(RetryAfterPolicy.delaySeconds(retryAfter: "15") == 15)
    #expect(RetryAfterPolicy.delaySeconds(retryAfter: "120") == 60)
    #expect(RetryAfterPolicy.delaySeconds(retryAfter: nil) == 2)
}
