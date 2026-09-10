import Foundation

struct ClientScope: Equatable, Sendable {
    let userID: UUID
    let language: String

    init(userID: UUID, language: String) {
        self.userID = userID
        self.language = Self.canonicalLanguage(language)
    }

    var identity: String { "\(userID.uuidString).\(language)" }
    var recipeCacheKey: String { "reciapp.recipeCache.v3.\(identity)" }
    var folderCacheKey: String { "reciapp.folderCache.v3.\(userID.uuidString)" }

    private static func canonicalLanguage(_ raw: String) -> String {
        let normalized = raw.replacingOccurrences(of: "_", with: "-").lowercased()
        switch normalized.split(separator: "-").first.map(String.init) ?? normalized {
        case "es": return "es-ES"
        case "fr": return "fr-FR"
        case "pt": return "pt-BR"
        case "de": return "de"
        case "it": return "it"
        default: return "en-US"
        }
    }
}

struct ClientStatePolicy: Sendable {
    private(set) var scope: ClientScope?
    private(set) var generation = 0
    private(set) var lastForegroundRefresh: Date?

    mutating func activate(_ newScope: ClientScope) -> Bool {
        guard scope != newScope else { return false }
        scope = newScope
        generation += 1
        lastForegroundRefresh = nil
        return true
    }

    mutating func invalidate() {
        scope = nil
        generation += 1
        lastForegroundRefresh = nil
    }

    func accepts(generation expectedGeneration: Int, scope expectedScope: ClientScope) -> Bool {
        generation == expectedGeneration && scope == expectedScope
    }

    mutating func shouldRefreshForeground(at now: Date, cooldown: TimeInterval = 30) -> Bool {
        if let lastForegroundRefresh, now.timeIntervalSince(lastForegroundRefresh) < cooldown { return false }
        lastForegroundRefresh = now
        return true
    }
}

enum CacheMigrationPolicy {
    static let marker = "reciapp.cacheMigration.v3"
    static let exactLegacyKeys = [
        "reciapp.recipeCategories.v1",
        "reciapp.customCategories.v1",
        "reciapp.categoryColors.v1",
        "reciapp.recipeCache.v1",
        "reciapp.recipeCategories.v2",
        "reciapp.customCategories.v2",
        "reciapp.categoryColors.v2",
    ]

    static func keysToRemove(from keys: some Sequence<String>) -> Set<String> {
        Set(keys.filter {
            exactLegacyKeys.contains($0)
                || $0.hasPrefix("reciapp.recipeCache.v1.")
                || $0.hasPrefix("reciapp.recipeCache.v2.")
                || $0.hasPrefix("reciapp.folderCache.v1.")
                || $0.hasPrefix("reciapp.folderCache.v2.")
        })
    }
}

enum RecipeAnnotationPolicy {
    static let tagMaxLength = 20
    static let tagMaxCount = 6

    static func cleanedTag(_ raw: String) -> String? {
        let clean = String(raw.trimmingCharacters(in: .whitespacesAndNewlines).prefix(tagMaxLength))
        return clean.isEmpty ? nil : clean
    }

    static func adding(_ raw: String, to tags: [String]) -> [String] {
        guard let tag = cleanedTag(raw) else { return tags }
        if tags.contains(where: { $0.caseInsensitiveCompare(tag) == .orderedSame }) {
            return tags
        }
        guard tags.count < tagMaxCount else { return tags }
        return tags + [tag]
    }

    static func removing(_ tag: String, from tags: [String]) -> [String] {
        tags.filter { $0.caseInsensitiveCompare(tag) != .orderedSame }
    }

    static func pruned(
        liveRecipeIDs: Set<UUID>,
        favorites: Set<UUID>,
        tags: [UUID: [String]],
        pruneMissing: Bool
    ) -> (favorites: Set<UUID>, tags: [UUID: [String]]) {
        guard pruneMissing else { return (favorites, tags) }
        return (
            favorites.intersection(liveRecipeIDs),
            tags.filter { liveRecipeIDs.contains($0.key) }
        )
    }
}

enum FolderAssignmentPolicy {
    static func reconciled(
        liveRecipeIDs: Set<UUID>,
        assignments: [UUID: String],
        customFolders: [String],
        uncategorized: String,
        pruneMissing: Bool = true
    ) -> [UUID: String] {
        let validFolders = Set(customFolders).union([uncategorized])
        var result = pruneMissing
            ? [:]
            : assignments.mapValues { validFolders.contains($0) ? $0 : uncategorized }
        for recipeID in liveRecipeIDs {
            let assigned = assignments[recipeID]
            result[recipeID] = assigned.flatMap { validFolders.contains($0) ? $0 : nil } ?? uncategorized
        }
        return result
    }
}

enum FolderHierarchyPolicy {
    static func containsDuplicate(_ name: String, folders: [String], excluding: String? = nil) -> Bool {
        folders.contains { candidate in
            candidate != excluding && candidate.localizedCaseInsensitiveCompare(name) == .orderedSame
        }
    }

    static func canMove(_ folder: String, to parent: String?, parents: [String: String]) -> Bool {
        guard let parent else { return true }
        guard parent != folder else { return false }

        var current: String? = parent
        var visited = Set<String>()
        while let candidate = current {
            guard visited.insert(candidate).inserted else { return false }
            if candidate == folder { return false }
            current = parents[candidate]
        }
        return true
    }

    static func moving(_ folder: String, to parent: String?, parents: [String: String]) -> [String: String]? {
        guard canMove(folder, to: parent, parents: parents) else { return nil }
        var result = parents
        if let parent {
            result[folder] = parent
        } else {
            result.removeValue(forKey: folder)
        }
        return result
    }

    static func promotingChildren(of folder: String, parents: [String: String]) -> [String: String] {
        var result = parents
        let promotedParent = result.removeValue(forKey: folder)
        let children = result.compactMap { $0.value == folder ? $0.key : nil }
        for child in children {
            if let promotedParent {
                result[child] = promotedParent
            } else {
                result.removeValue(forKey: child)
            }
        }
        return result
    }

    static func orderedChildren(
        of parent: String?,
        folders: [String],
        parents: [String: String]
    ) -> [String] {
        folders.filter { parents[$0] == parent }
    }

    static func sanitizedParents(folders: [String], parents: [String: String]) -> [String: String] {
        let validFolders = Set(folders)
        var result: [String: String] = [:]
        for folder in folders {
            guard let parent = parents[folder], validFolders.contains(parent) else { continue }
            guard canMove(folder, to: parent, parents: result) else { continue }
            result[folder] = parent
        }
        return result
    }
}

enum CacheRefreshPolicy {
    /// A decoded successful response, including `[]`, replaces cache. A missing value
    /// represents transport or decoding failure and preserves last known data.
    static func library<Value>(cached: [Value], successfulResponse: [Value]?) -> [Value] {
        successfulResponse ?? cached
    }
}

enum IngredientSectionPolicy {
    static func displayed(flat: [Ingredient], sections: [IngredientSection]) -> [IngredientSection] {
        let nonempty = sections.filter { !$0.ingredients.isEmpty }
        if !nonempty.isEmpty { return nonempty }
        return flat.isEmpty ? [] : [IngredientSection(title: "Ingredients", ingredients: flat)]
    }

    static func flattened(flat: [Ingredient], sections: [IngredientSection]) -> [Ingredient] {
        displayed(flat: flat, sections: sections).flatMap(\.ingredients)
    }
}

enum CachedResourceDecision<Value> {
    case fetch
    case cached(Value, shouldRevalidate: Bool)
}

struct DetailRevalidationPolicy: Sendable {
    private var started = Set<String>()

    mutating func decision<Value>(cached: Value?, recipeID: UUID, scope: ClientScope) -> CachedResourceDecision<Value> {
        guard let cached else { return .fetch }
        return .cached(cached, shouldRevalidate: shouldStart(recipeID: recipeID, scope: scope))
    }

    mutating func shouldStart(recipeID: UUID, scope: ClientScope) -> Bool {
        started.insert("\(recipeID.uuidString).\(scope.identity)").inserted
    }

    mutating func reset() { started.removeAll() }
}

struct SharedTaskCoordinator<Key: Hashable & Sendable, Value: Sendable, Failure: Error>: Sendable {
    struct Entry: Sendable {
        let id: UUID
        let task: Task<Value, Failure>
    }

    private var entries: [Key: Entry] = [:]

    var count: Int { entries.count }

    func entry(for key: Key) -> Entry? { entries[key] }

    mutating func acquire(for key: Key, create: () -> Task<Value, Failure>) -> Entry {
        if let existing = entries[key] { return existing }
        let entry = Entry(id: UUID(), task: create())
        entries[key] = entry
        return entry
    }

    mutating func release(key: Key, id: UUID) {
        guard entries[key]?.id == id else { return }
        entries[key] = nil
    }

    mutating func cancelAll() {
        entries.values.forEach { $0.task.cancel() }
        entries.removeAll()
    }
}

struct AuthRefreshKey: Hashable, Sendable {
    let rejectedToken: String
    let userID: UUID
    let generation: Int
}

struct UnauthorizedTokenPolicy: Sendable {
    private var completed = Set<String>()
    private var completionOrder: [String] = []
    private let capacity = 32

    func canStartRefresh(for token: String) -> Bool { !completed.contains(token) }
    mutating func finishRefresh(for token: String) {
        guard completed.insert(token).inserted else { return }
        completionOrder.append(token)
        if completionOrder.count > capacity {
            completed.remove(completionOrder.removeFirst())
        }
    }
}

enum ScopeGuardPolicy {
    static func accepts(
        expectedGeneration: Int,
        expectedIdentity: String?,
        currentGeneration: Int,
        currentIdentity: String?
    ) -> Bool {
        expectedGeneration == currentGeneration && expectedIdentity == currentIdentity
    }
}

enum AuthRecoveryScopePolicy {
    static func canUseToken(
        expectedUserID: UUID,
        expectedGeneration: Int,
        currentUserID: UUID?,
        currentGeneration: Int
    ) -> Bool {
        expectedUserID == currentUserID && expectedGeneration == currentGeneration
    }
}

enum SessionRestorePolicy {
    static func preservesLocalSession(hasExistingSession: Bool, missingSessionError: Bool) -> Bool {
        hasExistingSession && !missingSessionError
    }
}

enum LogoutOrderingPolicy {
    static func clearBeforeRemote(
        clear: () -> Void,
        remote: () async -> Void
    ) async {
        clear()
        await remote()
    }
}

enum RequestRetryPolicy {
    static func maximumAttempts(method: String) -> Int {
        switch method.uppercased() {
        case "GET", "HEAD", "OPTIONS": return 3
        default: return 1
        }
    }
}

enum APIErrorAction: Equatable {
    case reauthenticate
    case presentPaywall
    case showFairUse
    case showForbidden
    case showNotFound
    case correctInput
    case waitAndRetry
    case keepDataAndRetry
    case showJobFailure
    case showGeneric
}

enum APIErrorBehavior {
    static func action(status: Int, code: String?) -> APIErrorAction {
        if status == 401 { return .reauthenticate }
        if status == 200 && code == "JOB_FAILED" { return .showJobFailure }
        if status == 403 {
            switch code {
            case "FREE_WEEKLY_LIMIT": return .presentPaywall
            case "PRO_FAIR_USE_LIMIT": return .showFairUse
            default: return .showForbidden
            }
        }
        if status == 404 { return .showNotFound }
        if status == 413 || status == 422 { return .correctInput }
        if status == 429 { return .waitAndRetry }
        if status == 408 || status >= 500 { return .keepDataAndRetry }
        return .showGeneric
    }
}

enum APIErrorDetailParser {
    struct Parsed: Equatable {
        var code: String?
        var message: String
    }

    static func parse(data: Data, status: Int) -> Parsed {
        let fallback = "HTTP \(status)"
        guard let object = try? JSONSerialization.jsonObject(with: data) else {
            return Parsed(code: nil, message: fallback)
        }
        if let dict = object as? [String: Any] {
            return parseDetail(dict["detail"], fallback: fallback)
        }
        return Parsed(code: nil, message: fallback)
    }

    static func parseDetail(_ detail: Any?, fallback: String) -> Parsed {
        if let text = detail as? String, !text.isEmpty {
            return Parsed(code: nil, message: text)
        }
        if let fields = detail as? [String: Any] {
            let code = fields["code"] as? String
            let message = (fields["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? fallback
            return Parsed(code: code, message: message)
        }
        if let list = detail as? [Any] {
            let messages = list.compactMap { item -> String? in
                if let text = item as? String, !text.isEmpty { return text }
                if let fields = item as? [String: Any] {
                    return (fields["msg"] as? String) ?? (fields["message"] as? String)
                }
                return nil
            }.filter { !$0.isEmpty }
            if let first = messages.first {
                return Parsed(code: nil, message: messages.count == 1 ? first : messages.joined(separator: " "))
            }
        }
        return Parsed(code: nil, message: fallback)
    }
}

enum JobFollowPolicy {
    static func persistedID(jobID: UUID, nextJobID: UUID?) -> UUID {
        nextJobID ?? jobID
    }

    enum Outcome: Equatable {
        case succeeded
        case failed
        case wait
        case invalid
    }

    static func outcome(status: String, hasRecipe: Bool) -> Outcome {
        switch status {
        case "failed":
            return .failed
        case "completed":
            return hasRecipe ? .succeeded : .wait
        case "pending", "processing":
            return .wait
        default:
            return .invalid
        }
    }
}

struct PersistedImportJob: Codable, Equatable, Sendable {
    var jobID: UUID
    var language: String
    var userID: UUID
    var sourceURL: String?
}

enum ImportJobStore {
    static func key(userID: UUID) -> String {
        "reciapp.importJob.v1.\(userID.uuidString)"
    }

    static func save(_ job: PersistedImportJob, defaults: UserDefaults = .standard) {
        defaults.set(try? JSONEncoder().encode(job), forKey: key(userID: job.userID))
    }

    static func load(userID: UUID, defaults: UserDefaults = .standard) -> PersistedImportJob? {
        guard let data = defaults.data(forKey: key(userID: userID)) else { return nil }
        return try? JSONDecoder().decode(PersistedImportJob.self, from: data)
    }

    static func clear(userID: UUID, defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key(userID: userID))
    }
}

enum ImportJobRetentionPolicy {
    static func shouldRetainForResume(status: Int, code: String?) -> Bool {
        switch APIErrorBehavior.action(status: status, code: code) {
        case .waitAndRetry, .keepDataAndRetry, .reauthenticate:
            return true
        case .presentPaywall, .showFairUse, .showForbidden, .showNotFound,
             .correctInput, .showJobFailure, .showGeneric:
            return false
        }
    }

    static func shouldRetainURLError(_ code: URLError.Code) -> Bool {
        switch code {
        case .timedOut, .cannotFindHost, .cannotConnectToHost,
             .networkConnectionLost, .dnsLookupFailed,
             .notConnectedToInternet, .internationalRoamingOff,
             .callIsActive, .dataNotAllowed, .secureConnectionFailed,
             .cannotLoadFromNetwork, .backgroundSessionWasDisconnected:
            return true
        default:
            return false
        }
    }

    static func shouldRetryTransport(_ error: Error) -> Bool {
        if error is CancellationError { return false }
        if let urlError = error as? URLError {
            return shouldRetainURLError(urlError.code)
        }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain {
            return shouldRetainURLError(URLError.Code(rawValue: nsError.code))
        }
        if nsError.domain == NSPOSIXErrorDomain {
            guard let posix = POSIXError.Code(rawValue: Int32(nsError.code)) else { return false }
            switch posix {
            case .EAGAIN, .EPIPE, .EIO, .ENETDOWN, .ENETUNREACH,
                 .EHOSTDOWN, .EHOSTUNREACH, .ECONNREFUSED, .ECONNRESET,
                 .ECONNABORTED, .ETIMEDOUT, .ENOTCONN:
                return true
            default:
                return false
            }
        }
        return false
    }
}

enum ImportQueueErrorPolicy {
    enum Disposition: Equatable {
        case retryLater
        case skipItem
        case failItem
        case stopForUser
    }

    static func disposition(action: APIErrorAction) -> Disposition {
        switch action {
        case .waitAndRetry, .keepDataAndRetry, .showGeneric:
            return .retryLater
        case .correctInput:
            return .skipItem
        case .showJobFailure, .showNotFound:
            return .failItem
        case .presentPaywall, .showFairUse, .showForbidden, .reauthenticate:
            return .stopForUser
        }
    }

    static func disposition(status: Int, code: String?) -> Disposition {
        disposition(action: APIErrorBehavior.action(status: status, code: code))
    }
}

enum ImportQueueDrainPolicy {
    static func backoffSeconds(attempt: Int, cap: Double = 30) -> Double {
        min(Double(1 << min(max(attempt, 1), 10)), cap)
    }

    static func hasWork(inboxRemaining: Bool, serverJobCount: Int, hasPersistedJob: Bool) -> Bool {
        inboxRemaining || serverJobCount > 0 || hasPersistedJob
    }
}

enum RetryAfterPolicy {
    static func delaySeconds(retryAfter: String?, fallback: Double = 2, cap: Double = 60) -> Double {
        if let retryAfter, let seconds = Double(retryAfter) {
            return min(max(seconds, 0), cap)
        }
        return fallback
    }
}

struct ShareDelivery: Codable, Equatable, Identifiable, Sendable {
    let id: UUID
    let url: String
    let language: String
    let createdAt: Date
}

struct ShareInboxEnqueueResult: Equatable {
    var inbox: [ShareDelivery]
    var delivery: ShareDelivery
    var isDuplicate: Bool
}

enum ShareInboxPolicy {
    static let duplicateWindow: TimeInterval = 3
    static let maxPending = 20
    static let maxProcessed = 50

    static func enqueue(
        url: String,
        language: String,
        now: Date,
        inbox: [ShareDelivery],
        id: UUID = UUID()
    ) -> ShareInboxEnqueueResult {
        if let existing = inbox.last(where: {
            $0.url == url && now.timeIntervalSince($0.createdAt) < duplicateWindow
        }) {
            return ShareInboxEnqueueResult(inbox: inbox, delivery: existing, isDuplicate: true)
        }
        let delivery = ShareDelivery(id: id, url: url, language: language, createdAt: now)
        var next = inbox
        next.append(delivery)
        if next.count > maxPending {
            next.removeFirst(next.count - maxPending)
        }
        return ShareInboxEnqueueResult(inbox: next, delivery: delivery, isDuplicate: false)
    }

    static func removing(_ id: UUID, from inbox: [ShareDelivery]) -> [ShareDelivery] {
        inbox.filter { $0.id != id }
    }

    static func rememberProcessed(_ id: UUID, processed: [UUID]) -> [UUID] {
        var next = processed
        if !next.contains(id) { next.append(id) }
        if next.count > maxProcessed {
            next.removeFirst(next.count - maxProcessed)
        }
        return next
    }
}

enum URLNormalizePolicy {
    private static let urlPattern = #"https?://[^\s<>\"']+"#

    static func normalizeAll(_ raw: String, supportedHosts: [String]) -> [String] {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }

        var candidates: [String] = []
        let regex = try? NSRegularExpression(pattern: urlPattern, options: [])
        let range = NSRange(trimmed.startIndex..<trimmed.endIndex, in: trimmed)
        if let regex {
            for match in regex.matches(in: trimmed, options: [], range: range) {
                if let swiftRange = Range(match.range, in: trimmed) {
                    candidates.append(String(trimmed[swiftRange]))
                }
            }
        }
        if candidates.isEmpty {
            candidates = [trimmed]
        }

        var seen = Set<String>()
        var result: [String] = []
        for candidate in candidates {
            guard let normalized = normalizeOne(candidate, supportedHosts: supportedHosts) else { continue }
            if seen.insert(normalized).inserted {
                result.append(normalized)
            }
        }
        return result
    }

    static func normalizeOne(_ raw: String, supportedHosts: [String]) -> String? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }
        s = s.trimmingCharacters(in: CharacterSet(charactersIn: "<>\"'.,);"))
        if !s.contains("://") {
            s = "https://" + s
        }
        guard let url = URL(string: s), let host = url.host?.lowercased(), !host.isEmpty else {
            return nil
        }
        let hostOk = supportedHosts.contains(where: { host == $0 || host.hasSuffix(".\($0)") })
        guard hostOk else { return nil }
        return s
    }
}
