import Foundation

enum MeasurementUnitKind: Equatable {
    case mass
    case volume
    case count
    case unknown
}

enum MeasurementConversion {
    // Grams per millilitre for common ingredients (volume ↔ mass only when listed).
    private static let densityGPerMl: [String: Double] = [
        "water": 1.0, "agua": 1.0, "eau": 1.0, "acqua": 1.0, "wasser": 1.0,
        "milk": 1.03, "leche": 1.03, "lait": 1.03, "latte": 1.03, "milch": 1.03,
        "oil": 0.92, "olive oil": 0.91, "aceite": 0.92, "aceite de oliva": 0.91,
        "huile": 0.92, "olio": 0.92, "öl": 0.92,
        "flour": 0.53, "all-purpose flour": 0.53, "harina": 0.53, "farine": 0.53,
        "farina": 0.53, "mehl": 0.53,
        "sugar": 0.85, "white sugar": 0.85, "azúcar": 0.85, "azucar": 0.85,
        "sucre": 0.85, "zucchero": 0.85, "zucker": 0.85,
        "butter": 0.96, "mantequilla": 0.96, "beurre": 0.96, "burro": 0.96,
        "honey": 1.42, "miel": 1.42,
        "cream": 0.99, "nata": 0.99, "crème": 0.99, "panna": 0.99,
        "rice": 0.85, "arroz": 0.85, "riz": 0.85, "riso": 0.85, "reis": 0.85,
        "salt": 1.2, "sal": 1.2, "sel": 1.2, "sale": 1.2, "salz": 1.2,
        "cocoa": 0.5, "cacao": 0.5,
        "yogurt": 1.05, "yogur": 1.05, "yoghurt": 1.05,
    ]

    private static let countUnits: Set<String> = [
        "item", "items", "unit", "units", "ud", "uds", "unidad", "unidades",
        "piece", "pieces", "pieza", "piezas", "pc", "pcs", "each",
        "egg", "eggs", "huevo", "huevos", "clove", "cloves", "diente", "dientes",
        "can", "cans", "lata", "latas", "slice", "slices", "rodaja", "rodajas",
        "sprig", "sprigs", "ramita", "ramitas", "handful", "handfuls", "puñado", "puñados",
        "bunch", "bunches", "manojo", "manojos", "leaf", "leaves", "hoja", "hojas",
        "stalk", "stalks", "tallo", "tallos", "pinch", "pinches", "pizca", "pizcas",
    ]

    private static let massCanonical: [String: (canonical: String, toGrams: Double)] = [
        "g": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "gr": ("g", 1),
        "gramo": ("g", 1), "gramos": ("g", 1), "gramme": ("g", 1), "grammes": ("g", 1),
        "kg": ("g", 1000), "kilogram": ("g", 1000), "kilograms": ("g", 1000),
        "kilo": ("g", 1000), "kilos": ("g", 1000),
        "oz": ("oz", 28.3495), "ounce": ("oz", 28.3495), "ounces": ("oz", 28.3495),
        "onza": ("oz", 28.3495), "onzas": ("oz", 28.3495),
        "lb": ("lb", 453.592), "lbs": ("lb", 453.592), "pound": ("lb", 453.592), "pounds": ("lb", 453.592),
        "libra": ("lb", 453.592), "libras": ("lb", 453.592),
    ]

    private static let volumeCanonical: [String: (canonical: String, toMl: Double)] = [
        "ml": ("ml", 1), "milliliter": ("ml", 1), "milliliters": ("ml", 1),
        "millilitre": ("ml", 1), "millilitres": ("ml", 1),
        "l": ("ml", 1000), "liter": ("ml", 1000), "liters": ("ml", 1000),
        "litre": ("ml", 1000), "litres": ("ml", 1000),
        "cup": ("cup", 240), "cups": ("cup", 240), "taza": ("cup", 240), "tazas": ("cup", 240),
        "tbsp": ("tbsp", 15), "tablespoon": ("tbsp", 15), "tablespoons": ("tbsp", 15),
        "cucharada": ("tbsp", 15), "cucharadas": ("tbsp", 15),
        "tsp": ("tsp", 5), "teaspoon": ("tsp", 5), "teaspoons": ("tsp", 5),
        "cucharadita": ("tsp", 5), "cucharaditas": ("tsp", 5),
        "fl oz": ("fl oz", 29.5735), "floz": ("fl oz", 29.5735),
        "fluid ounce": ("fl oz", 29.5735), "fluid ounces": ("fl oz", 29.5735),
    ]

    static func kind(of unit: String?) -> MeasurementUnitKind {
        let key = normalizeKey(unit)
        guard !key.isEmpty else { return .count }
        if countUnits.contains(key) { return .count }
        if massCanonical[key] != nil { return .mass }
        if volumeCanonical[key] != nil { return .volume }
        return .unknown
    }

    static func convertIngredient(
        _ ingredient: Ingredient,
        measurement: MeasurementSystem
    ) -> Ingredient {
        guard let qty = IngredientQuantityMathPublic.parse(ingredient.quantity),
              let unit = ingredient.unit, !unit.isEmpty else {
            return ingredient
        }
        let key = normalizeKey(unit)
        let nameKey = normalizeKey(ingredient.name)

        switch kind(of: unit) {
        case .count, .unknown:
            return ingredient
        case .mass:
            guard let entry = massCanonical[key] else { return ingredient }
            let grams = qty * entry.toGrams
            switch measurement {
            case .metric:
                if grams >= 1000 {
                    return Ingredient(name: ingredient.name, quantity: format(grams / 1000), unit: "kg")
                }
                return Ingredient(name: ingredient.name, quantity: format(grams), unit: "g")
            case .imperial:
                if grams >= 453.592 {
                    return Ingredient(name: ingredient.name, quantity: format(grams / 453.592), unit: "lb")
                }
                return Ingredient(name: ingredient.name, quantity: format(grams / 28.3495), unit: "oz")
            }
        case .volume:
            guard let entry = volumeCanonical[key] else { return ingredient }
            let ml = qty * entry.toMl
            switch measurement {
            case .metric:
                if let density = density(for: nameKey) {
                    let grams = ml * density
                    if grams >= 1000 {
                        return Ingredient(name: ingredient.name, quantity: format(grams / 1000), unit: "kg")
                    }
                    return Ingredient(name: ingredient.name, quantity: format(grams), unit: "g")
                }
                if ml >= 1000 {
                    return Ingredient(name: ingredient.name, quantity: format(ml / 1000), unit: "l")
                }
                return Ingredient(name: ingredient.name, quantity: format(ml), unit: "ml")
            case .imperial:
                if let density = density(for: nameKey), massCanonical[key] != nil {
                    // Already handled in mass branch.
                }
                let cups = ml / 240
                if cups >= 0.25 {
                    return Ingredient(name: ingredient.name, quantity: format(cups), unit: cups == 1 ? "cup" : "cups")
                }
                let tbsp = ml / 15
                if tbsp >= 1 {
                    return Ingredient(name: ingredient.name, quantity: format(tbsp), unit: "tbsp")
                }
                return Ingredient(name: ingredient.name, quantity: format(ml / 5), unit: "tsp")
            }
        }
    }

    static func convertQuantity(
        value: Double,
        fromUnit: String,
        toUnit: String,
        ingredientName: String
    ) -> Double? {
        let fromKey = normalizeKey(fromUnit)
        let toKey = normalizeKey(toUnit)
        let nameKey = normalizeKey(ingredientName)
        let fromKind = kind(of: fromUnit)
        let toKind = kind(of: toUnit)
        guard fromKind != .count, toKind != .count else { return nil }

        if fromKind == .mass, toKind == .mass,
           let from = massCanonical[fromKey], let to = massCanonical[toKey] {
            return value * from.toGrams / to.toGrams
        }
        if fromKind == .volume, toKind == .volume,
           let from = volumeCanonical[fromKey], let to = volumeCanonical[toKey] {
            return value * from.toMl / to.toMl
        }
        if fromKind == .volume, toKind == .mass,
           let from = volumeCanonical[fromKey], let to = massCanonical[toKey],
           let density = density(for: nameKey) {
            return value * from.toMl * density / to.toGrams
        }
        if fromKind == .mass, toKind == .volume,
           let from = massCanonical[fromKey], let to = volumeCanonical[toKey],
           let density = density(for: nameKey), density > 0 {
            return value * from.toGrams / density / to.toMl
        }
        return nil
    }

    static func compatibleUnits(for ingredient: Ingredient, measurement: MeasurementSystem) -> [String] {
        let unit = ingredient.unit ?? ""
        let unitKind = kind(of: unit)
        let hasDensity = density(for: normalizeKey(ingredient.name)) != nil

        switch unitKind {
        case .count:
            return unit.isEmpty ? [] : [unit]
        case .mass:
            var units = measurement == .metric ? ["g", "kg"] : ["oz", "lb"]
            if hasDensity {
                units += measurement == .metric ? ["ml"] : ["cups", "tbsp", "tsp"]
            }
            return uniquePreserving(units, preferred: unit)
        case .volume:
            var units = measurement == .metric ? ["ml", "l"] : ["cups", "tbsp", "tsp", "fl oz"]
            if hasDensity {
                units += measurement == .metric ? ["g", "kg"] : ["oz", "lb"]
            }
            return uniquePreserving(units, preferred: unit)
        case .unknown:
            return unit.isEmpty ? [] : [unit]
        }
    }

    static func convertTemperatures(in text: String, to unit: TemperatureUnit) -> String {
        var result = text
        let patterns: [(Regex<(Substring, Substring, Substring?)>, TemperatureUnit)] = []
        _ = patterns

        // °C → °F
        if unit == .fahrenheit {
            result = replaceTemperatures(in: result, fromSymbol: "C", toSymbol: "F") { c in
                c * 9 / 5 + 32
            }
        } else {
            result = replaceTemperatures(in: result, fromSymbol: "F", toSymbol: "C") { f in
                (f - 32) * 5 / 9
            }
        }
        return result
    }

    static func convertSections(
        _ sections: [IngredientSection],
        measurement: MeasurementSystem
    ) -> [IngredientSection] {
        sections.map { section in
            IngredientSection(
                title: section.title,
                ingredients: section.ingredients.map { convertIngredient($0, measurement: measurement) }
            )
        }
    }

    static func format(_ value: Double) -> String {
        IngredientQuantityMathPublic.format(value, unit: nil)
    }

    // MARK: - Helpers

    private static func density(for nameKey: String) -> Double? {
        if let exact = densityGPerMl[nameKey] { return exact }
        for (key, value) in densityGPerMl where nameKey.contains(key) || key.contains(nameKey) {
            return value
        }
        return nil
    }

    private static func normalizeKey(_ raw: String?) -> String {
        (raw ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .folding(options: .diacriticInsensitive, locale: .current)
    }

    private static func uniquePreserving(_ units: [String], preferred: String) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        let preferredKey = normalizeKey(preferred)
        if !preferred.isEmpty {
            result.append(preferred)
            seen.insert(preferredKey)
        }
        for unit in units {
            let key = normalizeKey(unit)
            if seen.insert(key).inserted {
                result.append(unit)
            }
        }
        return result
    }

    private static func replaceTemperatures(
        in text: String,
        fromSymbol: String,
        toSymbol: String,
        convert: (Double) -> Double
    ) -> String {
        let pattern = #"(\d+(?:[.,]\d+)?)\s*°?\s*"# + fromSymbol + #"(?![a-zA-Z])"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return text
        }
        let ns = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: ns.length))
        var output = text
        for match in matches.reversed() {
            guard match.numberOfRanges >= 2,
                  let fullRange = Range(match.range, in: output),
                  let numRange = Range(match.range(at: 1), in: output),
                  let value = Double(output[numRange].replacingOccurrences(of: ",", with: ".")) else {
                continue
            }
            let converted = convert(value).rounded()
            output.replaceSubrange(fullRange, with: "\(Int(converted))°\(toSymbol)")
        }
        return output
    }
}

/// Shared quantity parse/format used by conversion + adjust UI.
enum IngredientQuantityMathPublic {
    static func parse(_ rawValue: String?) -> Double? {
        guard let rawValue else { return nil }
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }

        let normalized = value.replacingOccurrences(of: ",", with: ".")
        if let decimal = Double(normalized) {
            return decimal
        }

        let fraction = normalized.split(separator: "/", omittingEmptySubsequences: true)
        guard fraction.count == 2,
              let numerator = Double(String(fraction[0]).trimmingCharacters(in: .whitespaces)),
              let denominator = Double(String(fraction[1]).trimmingCharacters(in: .whitespaces)),
              denominator != 0 else {
            return nil
        }
        return numerator / denominator
    }

    static func format(_ value: Double, unit: String?) -> String {
        let rounded: Double
        if MeasurementConversion.kind(of: unit) == .count {
            rounded = value > 0 ? max(1, value.rounded()) : 0
        } else {
            rounded = (value * 100).rounded() / 100
        }

        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: AppLanguageStore.current.localeIdentifier)
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = false
        formatter.minimumFractionDigits = 0
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: rounded)) ?? String(rounded)
    }
}

#if DEBUG
enum MeasurementConversionSelfCheck {
    static func run() {
        let water = Ingredient(name: "water", quantity: "1", unit: "cup")
        let metric = MeasurementConversion.convertIngredient(water, measurement: .metric)
        assert(metric.unit == "g" || metric.unit == "ml", "cup water should convert under metric")
        if metric.unit == "g", let q = IngredientQuantityMathPublic.parse(metric.quantity) {
            assert(abs(q - 240) < 1, "1 cup water ≈ 240 g")
        }
        let eggs = Ingredient(name: "eggs", quantity: "3", unit: "eggs")
        let eggsConverted = MeasurementConversion.convertIngredient(eggs, measurement: .metric)
        assert(eggsConverted.unit == "eggs", "count units stay")
        let text = MeasurementConversion.convertTemperatures(in: "Bake at 350°F for 20 min", to: .celsius)
        assert(text.contains("177°C") || text.contains("176°C"), "350°F → ~177°C, got \(text)")
    }
}
#endif
