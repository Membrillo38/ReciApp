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
        normalizeAll(raw).first
    }

    /// All supported https URLs in `raw`, unique, stable order.
    static func normalizeAll(_ raw: String) -> [String] {
        URLNormalizePolicy.normalizeAll(raw, supportedHosts: supportedHosts)
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
