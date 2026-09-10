import Foundation

enum RestStepClassifier {
    private static let restKeywords: [String] = [
        "reposar", "reposo", "nevera", "refriger", "enfriar", "descansar", "macerar", "marinar",
        "rest", "chill", "refrigerat", "fridge", "wait", "marinate", "soak", "sit for", "let sit",
        "let rest", "cool", "overnight", "leave to",
        "reposer", "frigidaire", "réfrigér",
        "riposare", "frigo", "refriger",
        "ruhen", "kühlschrank", "abkühlen",
    ]

    private static let cookVerbs: [String] = [
        "fry", "mix", "stir", "bake", "cook", "chop", "cut", "slice", "dice", "whisk", "blend",
        "saute", "sauté", "boil", "simmer", "roast", "grill", "sear", "knead", "pour", "add",
        "combine", "heat", "melt", "spread", "place", "transfer", "remove", "serve",
        "freír", "freir", "mezclar", "hornear", "cocinar", "cortar", "batir", "añadir", "anadir",
        "calentar", "hervir", "asar", "saltear", "remover", "servir", "incorporar",
        "faire frire", "mélanger", "cuire", "couper", "ajouter",
        "friggere", "mescolare", "cuocere", "tagliare", "aggiungere",
        "braten", "mischen", "backen", "kochen", "schneiden", "hinzufügen",
    ]

    static func isRestStep(_ step: Step) -> Bool {
        let text = step.text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .folding(options: .diacriticInsensitive, locale: .current)
        guard !text.isEmpty else { return false }

        let hasRestKeyword = restKeywords.contains { text.contains($0) }
        guard hasRestKeyword else { return false }

        let hasCookVerb = cookVerbs.contains { text.contains($0) }
        if hasCookVerb {
            // Long rest with incidental cook words still counts if duration is present
            // and text is short (mostly a wait instruction).
            guard step.durationMinutes != nil, text.count < 120 else { return false }
        }
        return true
    }

    static func displayLabel(for step: Step) -> String {
        if let minutes = step.durationMinutes {
            if minutes >= 60 {
                let hours = minutes / 60
                let rem = minutes % 60
                if rem == 0 {
                    return hours == 1
                        ? ReciLocalization.string("1 hour")
                        : String(format: ReciLocalization.string("%d hours"), hours)
                }
                return String(format: ReciLocalization.string("%dh %dm"), hours, rem)
            }
            return String(format: ReciLocalization.string("%d min"), minutes)
        }
        return step.text
    }
}
