import Foundation

enum TemperatureUnit: String, Codable, CaseIterable, Identifiable {
    case celsius
    case fahrenheit

    var id: Self { self }

    var title: String {
        switch self {
        case .celsius: return ReciLocalization.string("Celsius")
        case .fahrenheit: return ReciLocalization.string("Fahrenheit")
        }
    }

    var symbol: String {
        switch self {
        case .celsius: return "°C"
        case .fahrenheit: return "°F"
        }
    }
}

enum MeasurementSystem: String, Codable, CaseIterable, Identifiable {
    case metric
    case imperial

    var id: Self { self }

    var title: String {
        switch self {
        case .metric: return ReciLocalization.string("Metric")
        case .imperial: return ReciLocalization.string("Imperial")
        }
    }

    var detail: String {
        switch self {
        case .metric: return ReciLocalization.string("grams, millilitres")
        case .imperial: return ReciLocalization.string("ounces, cups")
        }
    }
}

struct UserPreferences: Codable, Equatable {
    var temperatureUnit: TemperatureUnit = .celsius
    var measurementSystem: MeasurementSystem = .metric
}

enum UserPreferencesStore {
    private static let keyPrefix = "reciapp.userPreferences.v1."

    static func isComplete(for userID: String) -> Bool {
        load(for: userID) != nil
    }

    static func load(for userID: String) -> UserPreferences? {
        guard let data = UserDefaults.standard.data(forKey: key(for: userID)) else {
            return nil
        }
        return try? JSONDecoder().decode(UserPreferences.self, from: data)
    }

    static func save(_ preferences: UserPreferences, for userID: String) {
        guard let data = try? JSONEncoder().encode(preferences) else { return }
        UserDefaults.standard.set(data, forKey: key(for: userID))
    }

    private static func key(for userID: String) -> String {
        keyPrefix + userID
    }
}

struct CookingProgress: Codable, Equatable {
    let selectedStepIndex: Int
    let completedStepOrders: Set<Int>
}

enum CookingProgressStore {
    private static let keyPrefix = "reciapp.cookingProgress.v1."

    static func load(for recipeID: UUID) -> CookingProgress? {
        guard let data = UserDefaults.standard.data(forKey: key(for: recipeID)) else {
            return nil
        }
        return try? JSONDecoder().decode(CookingProgress.self, from: data)
    }

    static func save(_ progress: CookingProgress, for recipeID: UUID) {
        guard let data = try? JSONEncoder().encode(progress) else { return }
        UserDefaults.standard.set(data, forKey: key(for: recipeID))
    }

    static func clear(for recipeID: UUID) {
        UserDefaults.standard.removeObject(forKey: key(for: recipeID))
    }

    private static func key(for recipeID: UUID) -> String {
        keyPrefix + recipeID.uuidString
    }
}
