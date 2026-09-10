import Foundation

struct HealthResponse: Decodable {
    let status: String
}

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
    let language: String
}

struct ExtractJobResponse: Codable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
    let progress: Int?
    let queued: Bool?
    let queuePosition: Int?
}

struct JobResponse: Codable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
    let recipe: RecipePublic?
    let recipeId: UUID?
    let error: String?
    let progress: Int?
    let nextJobId: UUID?
}

struct QueuedJobItem: Codable, Identifiable {
    let jobId: UUID
    let status: String
    let progress: Int
    let sourceUrl: String
    let queuePosition: Int
    let createdAt: String?
    let jobKind: String?

    var id: UUID { jobId }
}

struct QueuedJobsResponse: Codable {
    let items: [QueuedJobItem]
}

struct RecipeListResponse: Codable {
    let items: [RecipeSummary]
}

struct RecipeCategoryFolder: Identifiable, Hashable {
    let name: String
    let count: Int
    let colorHex: String

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
    let languageCode: String

    private enum CodingKeys: String, CodingKey {
        case id, title, platform, sourceUrl, thumbnailUrl, author, servings, prepMinutes, cookMinutes, savedAt, languageCode
    }

    init(
        id: UUID,
        title: String,
        platform: String,
        sourceUrl: String,
        thumbnailUrl: String?,
        author: String?,
        servings: Int?,
        prepMinutes: Int?,
        cookMinutes: Int?,
        savedAt: String,
        languageCode: String = "en-US"
    ) {
        self.id = id
        self.title = title
        self.platform = platform
        self.sourceUrl = sourceUrl
        self.thumbnailUrl = thumbnailUrl
        self.author = author
        self.servings = servings
        self.prepMinutes = prepMinutes
        self.cookMinutes = cookMinutes
        self.savedAt = savedAt
        self.languageCode = languageCode
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        title = try container.decode(String.self, forKey: .title)
        platform = try container.decode(String.self, forKey: .platform)
        sourceUrl = try container.decode(String.self, forKey: .sourceUrl)
        thumbnailUrl = try container.decodeIfPresent(String.self, forKey: .thumbnailUrl)
        author = try container.decodeIfPresent(String.self, forKey: .author)
        servings = try container.decodeIfPresent(Int.self, forKey: .servings)
        prepMinutes = try container.decodeIfPresent(Int.self, forKey: .prepMinutes)
        cookMinutes = try container.decodeIfPresent(Int.self, forKey: .cookMinutes)
        savedAt = try container.decode(String.self, forKey: .savedAt)
        languageCode = try container.decodeIfPresent(String.self, forKey: .languageCode) ?? "en-US"
    }
}

struct IngredientSection: Codable, Hashable, Identifiable {
    let title: String
    let ingredients: [Ingredient]

    var id: String { title }
}

struct RecipeTip: Codable, Hashable, Identifiable {
    let title: String?
    let text: String

    var id: String { "\(title ?? "")-\(text)" }
}

struct RecipePublic: Codable, Identifiable, Hashable {
    let id: UUID
    let title: String
    let ingredients: [Ingredient]
    let ingredientSections: [IngredientSection]
    let steps: [Step]
    let servings: Int?
    let prepMinutes: Int?
    let cookMinutes: Int?
    let tags: [String]
    let sourceUrl: String
    let platform: String
    let thumbnailUrl: String?
    let carouselImageUrls: [String]
    let author: String?
    let description: String?
    let tips: [RecipeTip]
    let languageCode: String

    init(
        id: UUID,
        title: String,
        ingredients: [Ingredient],
        ingredientSections: [IngredientSection] = [],
        steps: [Step],
        servings: Int?,
        prepMinutes: Int?,
        cookMinutes: Int?,
        tags: [String],
        sourceUrl: String,
        platform: String,
        thumbnailUrl: String?,
        carouselImageUrls: [String] = [],
        author: String?,
        description: String?,
        tips: [RecipeTip] = [],
        languageCode: String = "en-US"
    ) {
        self.id = id
        self.title = title
        self.ingredients = ingredients
        self.ingredientSections = ingredientSections
        self.steps = steps
        self.servings = servings
        self.prepMinutes = prepMinutes
        self.cookMinutes = cookMinutes
        self.tags = tags
        self.sourceUrl = sourceUrl
        self.platform = platform
        self.thumbnailUrl = thumbnailUrl
        self.carouselImageUrls = carouselImageUrls
        self.author = author
        self.description = description
        self.tips = tips
        self.languageCode = languageCode
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, ingredients, steps, servings, tags, platform, author, description, tips, languageCode
        case ingredientSections
        case prepMinutes
        case cookMinutes
        case sourceUrl
        case thumbnailUrl
        case carouselImageUrls
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        title = try container.decode(String.self, forKey: .title)
        ingredients = try container.decodeIfPresent([Ingredient].self, forKey: .ingredients) ?? []
        ingredientSections = try container.decodeIfPresent([IngredientSection].self, forKey: .ingredientSections) ?? []
        steps = try container.decodeIfPresent([Step].self, forKey: .steps) ?? []
        servings = try container.decodeIfPresent(Int.self, forKey: .servings)
        prepMinutes = try container.decodeIfPresent(Int.self, forKey: .prepMinutes)
        cookMinutes = try container.decodeIfPresent(Int.self, forKey: .cookMinutes)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        sourceUrl = try container.decode(String.self, forKey: .sourceUrl)
        platform = try container.decode(String.self, forKey: .platform)
        thumbnailUrl = try container.decodeIfPresent(String.self, forKey: .thumbnailUrl)
        carouselImageUrls = try container.decodeIfPresent([String].self, forKey: .carouselImageUrls) ?? []
        author = try container.decodeIfPresent(String.self, forKey: .author)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        tips = try container.decodeIfPresent([RecipeTip].self, forKey: .tips) ?? []
        languageCode = try container.decodeIfPresent(String.self, forKey: .languageCode) ?? "en-US"
    }
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

struct OkResponse: Decodable, Sendable {
    let ok: Bool
}

enum AppError: LocalizedError {
    case unauthorized
    case quota(QuotaErrorDetail)
    case fairUse(String)
    case forbidden(String)
    case notFound(String)
    case invalidInput(String)
    case rateLimited(String, retryAfter: String?)
    case unavailable(String)
    case jobFailed(String)
    case server(String)
    case transient(String)
    case noRecipe

    var errorDescription: String? {
        switch self {
        case .unauthorized:
            return ReciLocalization.string("Not signed in")
        case .quota(let detail):
            if detail.code == "FREE_WEEKLY_LIMIT", let limit = detail.freeLimit {
                return String(
                    format: ReciLocalization.string("Free plan: %d recipe(s) per week. Upgrade to Pro."),
                    limit
                )
            }
            return ReciLocalization.string(detail.message, fallback: ReciLocalization.string("We couldn't complete that action. Please try again."))
        case .fairUse(let message):
            return ReciLocalization.string(message, fallback: ReciLocalization.string("You've reached the temporary Pro usage limit. Try again later."))
        case .forbidden(let message):
            return ReciLocalization.string(message, fallback: ReciLocalization.string("You don't have access to this action."))
        case .notFound:
            return ReciLocalization.string("This recipe or import is no longer available.")
        case .invalidInput(let message):
            return ReciLocalization.string(message, fallback: ReciLocalization.string("This link isn't valid. Check it and try again."))
        case .rateLimited(let message, let retryAfter):
            if let retryAfter, let seconds = Int(retryAfter) {
                return String(
                    format: ReciLocalization.string("Too many requests. Wait %d seconds and try again."),
                    seconds
                )
            }
            return ReciLocalization.string(message, fallback: ReciLocalization.string("Too many requests. Wait and try again."))
        case .unavailable:
            return ReciLocalization.string("The service is temporarily unavailable. Your saved recipes are still here.")
        case .jobFailed(let message):
            return ReciLocalization.string(message, fallback: ReciLocalization.string("The import failed. The link may be private, deleted, or not a recipe."))
        case .server(let message):
            return Self.localizedServerMessage(message)
        case .transient(let message):
            return Self.localizedServerMessage(message)
        case .noRecipe:
            return ReciLocalization.string("No recipe in response")
        }
    }

    var retryAfter: String? {
        if case .rateLimited(_, let retryAfter) = self { return retryAfter }
        return nil
    }

    var apiAction: APIErrorAction {
        switch self {
        case .unauthorized: .reauthenticate
        case .quota: .presentPaywall
        case .fairUse: .showFairUse
        case .forbidden: .showForbidden
        case .notFound: .showNotFound
        case .invalidInput: .correctInput
        case .rateLimited: .waitAndRetry
        case .unavailable: .keepDataAndRetry
        case .jobFailed: .showJobFailure
        case .transient: .keepDataAndRetry
        case .server, .noRecipe: .showGeneric
        }
    }

    private static func localizedServerMessage(_ message: String) -> String {
        let missing = "\u{0000}"
        let localized = ReciLocalization.string(message, fallback: missing)
        if localized != missing { return localized }
        return ReciLocalization.string("We couldn't complete that action. Please try again.")
    }

    var isTransient: Bool {
        switch self {
        case .transient, .unavailable, .rateLimited:
            return true
        default:
            return false
        }
    }
}
