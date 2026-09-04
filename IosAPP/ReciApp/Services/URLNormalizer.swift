import Foundation

enum URLNormalizer {
    private static let supportedHosts = [
        "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
        "youtube.com", "youtu.be", "m.youtube.com",
        "instagram.com", "www.instagram.com",
        "facebook.com", "fb.watch", "m.facebook.com",
    ]

    /// Returns HTTPS URL string acceptable by the API, or nil.
    static func normalize(_ raw: String) -> String? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }

        // Share sheets sometimes wrap URL in quotes or angle brackets
        s = s.trimmingCharacters(in: CharacterSet(charactersIn: "<>\"'"))

        if !s.contains("://") {
            s = "https://" + s
        }

        guard let url = URL(string: s), let host = url.host?.lowercased(), !host.isEmpty else {
            return nil
        }

        let hostOk = supportedHosts.contains(where: { host == $0 || host.hasSuffix(".\($0)") || host.contains($0) })
        guard hostOk else { return nil }

        return s
    }

    static func platformLabel(_ url: String) -> String {
        let lower = url.lowercased()
        if lower.contains("tiktok") { return "tiktok" }
        if lower.contains("youtu") { return "youtube" }
        if lower.contains("instagram") { return "instagram" }
        if lower.contains("facebook") || lower.contains("fb.watch") { return "facebook" }
        return "unknown"
    }
}
