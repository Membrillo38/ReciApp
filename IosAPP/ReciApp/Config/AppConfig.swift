import Foundation

enum AppConfig {
    static let apiBaseURL = URL(string: "https://reciapp-4ih5.onrender.com")!
    static let superwallPublicKey = "pk_3QyV6dXg2nPMj9gDTpZkF"
    static let pollIntervalSeconds: UInt64 = 2
    // Backend allows 10-minute media processing; keep a small network margin.
    static let maxPollAttempts = 330
}

enum DevConfig {
    /// Keep admin-only calls disabled in the shipped app.
    static let autoGrantPro = false
}
