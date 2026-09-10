import Foundation

struct Ingredient: Codable, Hashable, Identifiable {
    var id: String { "\(name)-\(quantity ?? "")-\(unit ?? "")" }
    let name: String
    let quantity: String?
    let unit: String?
}

struct IngredientSection: Codable, Hashable, Identifiable {
    let title: String
    let ingredients: [Ingredient]
    var id: String { title }
}
