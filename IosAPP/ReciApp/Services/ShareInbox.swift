import Foundation

enum ShareInbox {
    static let pendingKey = "reciapp.shareInbox.v1"
    static let processedKey = "reciapp.shareProcessed.v1"

    private static var defaults: UserDefaults {
        UserDefaults(suiteName: AppLanguageStore.appGroupIdentifier) ?? .standard
    }

    @discardableResult
    static func enqueue(raw: String, language: String, now: Date = Date()) -> ShareDelivery? {
        guard let url = URLNormalizer.normalize(raw) else { return nil }
        let result = ShareInboxPolicy.enqueue(
            url: url,
            language: language,
            now: now,
            inbox: pending(defaults: defaults)
        )
        save(result.inbox, defaults: defaults)
        return result.delivery
    }

    static func pending(defaults: UserDefaults? = nil) -> [ShareDelivery] {
        let store = defaults ?? Self.defaults
        guard let data = store.data(forKey: pendingKey) else { return [] }
        return (try? JSONDecoder().decode([ShareDelivery].self, from: data)) ?? []
    }

    static func takeUnprocessed(defaults: UserDefaults? = nil) -> [ShareDelivery] {
        let store = defaults ?? Self.defaults
        let processed = processedIDs(defaults: store)
        return pending(defaults: store).filter { !processed.contains($0.id) }
    }

    static func markProcessed(_ id: UUID, defaults: UserDefaults? = nil) {
        let store = defaults ?? Self.defaults
        save(ShareInboxPolicy.removing(id, from: pending(defaults: store)), defaults: store)
        let remembered = ShareInboxPolicy.rememberProcessed(id, processed: processedIDs(defaults: store))
        store.set(remembered.map(\.uuidString), forKey: processedKey)
    }

    static func containsProcessed(_ id: UUID, defaults: UserDefaults? = nil) -> Bool {
        processedIDs(defaults: defaults ?? Self.defaults).contains(id)
    }

    private static func processedIDs(defaults: UserDefaults) -> [UUID] {
        (defaults.stringArray(forKey: processedKey) ?? []).compactMap(UUID.init(uuidString:))
    }

    private static func save(_ inbox: [ShareDelivery], defaults: UserDefaults) {
        defaults.set(try? JSONEncoder().encode(inbox), forKey: pendingKey)
    }
}
