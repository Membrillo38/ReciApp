import Foundation

struct ShoppingListItem: Codable, Identifiable, Equatable, Hashable {
    let id: UUID
    var recipeID: UUID
    var recipeTitle: String
    var name: String
    var quantity: String?
    var unit: String?
    var isChecked: Bool

    init(
        id: UUID = UUID(),
        recipeID: UUID,
        recipeTitle: String,
        name: String,
        quantity: String?,
        unit: String?,
        isChecked: Bool = false
    ) {
        self.id = id
        self.recipeID = recipeID
        self.recipeTitle = recipeTitle
        self.name = name
        self.quantity = quantity
        self.unit = unit
        self.isChecked = isChecked
    }

    var mergeKey: String {
        let nameKey = name
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .folding(options: .diacriticInsensitive, locale: .current)
        let unitKey = (unit ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .folding(options: .diacriticInsensitive, locale: .current)
        return "\(nameKey)|\(unitKey)"
    }
}

struct MergedShoppingItem: Identifiable, Equatable {
    let id: String
    let name: String
    let quantity: String?
    let unit: String?
    let sourceTitles: [String]
    let sourceIDs: [UUID]
    var isChecked: Bool
}

enum ShoppingListStore {
    private static let keyPrefix = "reciapp.shoppingList.v1."

    static func load(for userID: String) -> [ShoppingListItem] {
        guard let data = UserDefaults.standard.data(forKey: key(for: userID)),
              let items = try? JSONDecoder().decode([ShoppingListItem].self, from: data) else {
            return []
        }
        return items
    }

    static func save(_ items: [ShoppingListItem], for userID: String) {
        guard let data = try? JSONEncoder().encode(items) else { return }
        UserDefaults.standard.set(data, forKey: key(for: userID))
    }

    static func add(
        ingredients: [Ingredient],
        recipeID: UUID,
        recipeTitle: String,
        for userID: String
    ) {
        var items = load(for: userID)
        for ingredient in ingredients where !ingredient.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            items.append(
                ShoppingListItem(
                    recipeID: recipeID,
                    recipeTitle: recipeTitle,
                    name: ingredient.name,
                    quantity: ingredient.quantity,
                    unit: ingredient.unit
                )
            )
        }
        save(items, for: userID)
    }

    static func remove(id: UUID, for userID: String) {
        var items = load(for: userID)
        items.removeAll { $0.id == id }
        save(items, for: userID)
    }

    static func remove(ids: [UUID], for userID: String) {
        var items = load(for: userID)
        let set = Set(ids)
        items.removeAll { set.contains($0.id) }
        save(items, for: userID)
    }

    static func toggle(id: UUID, for userID: String) {
        var items = load(for: userID)
        guard let index = items.firstIndex(where: { $0.id == id }) else { return }
        items[index].isChecked.toggle()
        save(items, for: userID)
    }

    static func toggleMerged(ids: [UUID], for userID: String) {
        var items = load(for: userID)
        let set = Set(ids)
        let allChecked = items.filter { set.contains($0.id) }.allSatisfy(\.isChecked)
        for index in items.indices where set.contains(items[index].id) {
            items[index].isChecked = !allChecked
        }
        save(items, for: userID)
    }

    static func clearChecked(for userID: String) {
        var items = load(for: userID)
        items.removeAll(\.isChecked)
        save(items, for: userID)
    }

    static func merged(from items: [ShoppingListItem]) -> [MergedShoppingItem] {
        var groups: [String: [ShoppingListItem]] = [:]
        var order: [String] = []
        for item in items {
            let key = item.mergeKey
            if groups[key] == nil {
                order.append(key)
                groups[key] = []
            }
            groups[key, default: []].append(item)
        }

        return order.compactMap { key in
            guard let group = groups[key], let first = group.first else { return nil }
            let quantities = group.compactMap { IngredientQuantityMathPublic.parse($0.quantity) }
            let quantity: String?
            if quantities.count == group.count, !quantities.isEmpty {
                quantity = IngredientQuantityMathPublic.format(quantities.reduce(0, +), unit: first.unit)
            } else if group.count == 1 {
                quantity = first.quantity
            } else {
                quantity = group.compactMap(\.quantity).joined(separator: " + ").nilIfEmpty
            }
            return MergedShoppingItem(
                id: key,
                name: first.name,
                quantity: quantity,
                unit: first.unit,
                sourceTitles: Array(Set(group.map(\.recipeTitle))).sorted(),
                sourceIDs: group.map(\.id),
                isChecked: group.allSatisfy(\.isChecked)
            )
        }
    }

    private static func key(for userID: String) -> String {
        keyPrefix + userID
    }
}

private extension String {
    var nilIfEmpty: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

private extension Array where Element == ShoppingListItem {
    mutating func removeAll(_ isChecked: KeyPath<ShoppingListItem, Bool>) {
        removeAll { $0[keyPath: isChecked] }
    }
}
