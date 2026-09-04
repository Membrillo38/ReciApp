import Foundation

struct MeResponse: Codable {
    let id: UUID
    let displayName: String?
    let isPro: Bool
    let proExpiresAt: String?
    let freeUsedThisWeek: Int
    let freeLimit: Int
    let freeRemaining: Int
    let proRemainingCents: Double?
}

struct ExtractRequest: Encodable {
    let url: String
}

struct ExtractJobResponse: Codable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
    let progress: Int?
}

struct JobResponse: Codable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
    let recipe: RecipePublic?
    let error: String?
    let progress: Int?
}

struct RecipeListResponse: Codable {
    let items: [RecipeSummary]
}

struct RecipeCategoryFolder: Identifiable, Hashable {
    let name: String
    let count: Int

    var id: String { name }
}

struct RecipeSummary: Codable, Identifiable, Hashable {
    let id: UUID
    let title: String
    let platform: String
    let sourceUrl: String
    let thumbnailUrl: String?
    let author: String?
    let servings: Int?
    let prepMinutes: Int?
    let cookMinutes: Int?
    let savedAt: String
}

struct RecipePublic: Codable, Identifiable, Hashable {
    let id: UUID
    let title: String
    let ingredients: [Ingredient]
    let steps: [Step]
    let servings: Int?
    let prepMinutes: Int?
    let cookMinutes: Int?
    let tags: [String]
    let sourceUrl: String
    let platform: String
    let thumbnailUrl: String?
    let author: String?
    let description: String?
}

struct Ingredient: Codable, Hashable, Identifiable {
    var id: String { "\(name)-\(quantity ?? "")-\(unit ?? "")" }
    let name: String
    let quantity: String?
    let unit: String?
}

struct Step: Codable, Hashable, Identifiable {
    var id: Int { order }
    let order: Int
    let text: String
    let durationMinutes: Int?
}

struct QuotaErrorDetail: Codable {
    let code: String
    let message: String
    let freeUsedThisWeek: Int?
    let freeLimit: Int?
}

struct APIErrorPayload: Codable {
    let detail: QuotaErrorDetail?
}

enum AppError: LocalizedError {
    case unauthorized
    case quota(QuotaErrorDetail)
    case server(String)
    case noRecipe

    var errorDescription: String? {
        switch self {
        case .unauthorized: "Not signed in"
        case .quota(let d): d.message
        case .server(let m): m
        case .noRecipe: "No recipe in response"
        }
    }
}
