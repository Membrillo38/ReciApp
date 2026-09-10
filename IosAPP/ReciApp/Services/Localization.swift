import Foundation

enum AppLanguage: String, CaseIterable, Codable, Identifiable {
    case system
    case enUS = "en-US"
    case frFR = "fr-FR"
    case ptBR = "pt-BR"
    case esES = "es-ES"
    case de, it

    var id: String { rawValue }

    static var supportedLanguages: [AppLanguage] {
        allCases.filter { $0 != .system }
    }

    static var resolvedSystem: AppLanguage {
        let preferred = Locale.preferredLanguages.first ?? Locale.current.identifier
        return language(for: preferred) ?? .enUS
    }

    static func language(for identifier: String) -> AppLanguage? {
        let normalized = identifier.replacingOccurrences(of: "_", with: "-")
        if let exact = supportedLanguages.first(where: { $0.rawValue.caseInsensitiveCompare(normalized) == .orderedSame }) {
            return exact
        }
        let base = normalized.split(separator: "-").first.map(String.init) ?? normalized
        if let baseMatch = supportedLanguages.first(where: { $0.rawValue.caseInsensitiveCompare(base) == .orderedSame }) {
            return baseMatch
        }
        switch base.lowercased() {
        case "en": return .enUS
        case "es": return .esES
        case "fr": return .frFR
        case "pt": return .ptBR
        default: return nil
        }
    }

    static func fromStoredValue(_ rawValue: String) -> AppLanguage {
        if rawValue == AppLanguage.system.rawValue {
            return .system
        }
        return language(for: rawValue) ?? .system
    }

    var localeIdentifier: String {
        self == .system ? Self.resolvedSystem.rawValue : rawValue
    }

    var serverCode: String {
        self == .system ? Self.resolvedSystem.rawValue : rawValue
    }

    var displayName: String {
        switch self {
        case .system: return ReciLocalization.string("System default")
        case .enUS: return "English"
        case .esES: return "Español"
        case .frFR: return "Français"
        case .de: return "Deutsch"
        case .it: return "Italiano"
        case .ptBR: return "Português"
        }
    }
}

enum AppLanguageStore {
    static let storageKey = "reciapp.language.v1"
    static let appGroupIdentifier = "group.com.membri.reciapp"

    private static var sharedDefaults: UserDefaults? {
        UserDefaults(suiteName: appGroupIdentifier)
    }

    static var selection: AppLanguage {
        get {
            let raw = sharedDefaults?.string(forKey: storageKey)
                ?? UserDefaults.standard.string(forKey: storageKey)
            guard let raw else { return .system }
            return AppLanguage.fromStoredValue(raw)
        }
        set {
            sharedDefaults?.set(newValue.rawValue, forKey: storageKey)
            UserDefaults.standard.set(newValue.rawValue, forKey: storageKey)
        }
    }

    static var current: AppLanguage {
        selection == .system ? .resolvedSystem : selection
    }
}

enum ReciLocalization {
    static func string(_ key: String, fallback: String? = nil) -> String {
        let resourceCodes = [
            AppLanguageStore.current.rawValue,
            AppLanguageStore.current.rawValue.split(separator: "-").first.map(String.init) ?? "",
        ]
        let missingValue = "\u{0000}"
        for code in resourceCodes where !code.isEmpty {
            guard let path = Bundle.main.path(forResource: code, ofType: "lproj"),
                  let bundle = Bundle(path: path) else { continue }
            let value = bundle.localizedString(forKey: key, value: missingValue, table: nil)
            if value != missingValue { return value }
        }
        return Bundle.main.localizedString(forKey: key, value: fallback ?? key, table: nil)
    }
}
