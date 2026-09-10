import Foundation

enum AppConfig {
    static let apiBaseURL = URL(string: "https://reciapp-4ih5.onrender.com")!
    static let supabaseURL = URL(string: "https://nzimdcjxgklopythnpfi.supabase.co")!
    static let supabaseAnonKey =
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im56aW1kY2p4Z2tsb3B5dGhucGZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNjE1ODksImV4cCI6MjEwMzkzNzU4OX0._7_828Cs63M7tWLT83DYmtpAYP_8ptDg2Gr_4hRdzGM"
    static let superwallPublicKey = "pk_3QyV6dXg2nPMj9gDTpZkF"
    static let pollIntervalSeconds: UInt64 = 2
    // Backend allows 10-minute media processing; keep a small network margin.
    static let maxPollAttempts = 330
}

enum DevConfig {
    /// Keep admin-only calls disabled in the shipped app.
    static let autoGrantPro = false
}
