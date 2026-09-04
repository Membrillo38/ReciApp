import Foundation
import OSLog

enum AppLogger {
    static let api = Logger(subsystem: "com.membri.reciapp", category: "api")
    static let auth = Logger(subsystem: "com.membri.reciapp", category: "auth")
    static let app = Logger(subsystem: "com.membri.reciapp", category: "app")
}

final class APIClient {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    func me(token: String) async throws -> MeResponse {
        try await get("/v1/me", token: token)
    }

    func myRecipes(token: String) async throws -> [RecipeSummary] {
        let res: RecipeListResponse = try await get("/v1/me/recipes", token: token)
        return res.items
    }

    func recipe(id: UUID, token: String) async throws -> RecipePublic {
        try await get("/v1/recipes/\(id.uuidString)", token: token)
    }

    func extract(url: String, token: String) async throws -> ExtractJobResponse {
        try await post("/v1/extract", body: ExtractRequest(url: url), token: token)
    }

    func job(id: UUID, token: String) async throws -> JobResponse {
        try await get("/v1/jobs/\(id.uuidString)", token: token)
    }

    func extractAndWait(
        url: String,
        token: String,
        onStatus: (@Sendable (String, Int) -> Void)? = nil
    ) async throws -> RecipePublic {
        let started = try await extract(url: url, token: token)
        onStatus?(started.cacheHit ? "cache hit" : "job \(started.status)", started.progress ?? 0)

        if started.status == "completed" {
            let j = try await job(id: started.jobId, token: token)
            guard let recipe = j.recipe else { throw AppError.noRecipe }
            return recipe
        }

        for attempt in 1...AppConfig.maxPollAttempts {
            let j = try await job(id: started.jobId, token: token)
            onStatus?("poll \(attempt): \(j.status)", j.progress ?? 0)
            switch j.status {
            case "completed":
                guard let recipe = j.recipe else { throw AppError.noRecipe }
                return recipe
            case "failed":
                throw AppError.server(j.error ?? "Extract failed")
            default:
                try await Task.sleep(nanoseconds: AppConfig.pollIntervalSeconds * 1_000_000_000)
            }
        }
        throw AppError.server("Timed out waiting for recipe")
    }

    func deleteRecipe(id: UUID, token: String) async throws {
        var req = URLRequest(url: AppConfig.apiBaseURL.appendingPathComponent("/v1/me/recipes/\(id.uuidString)"))
        req.httpMethod = "DELETE"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (_, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw AppError.server("Delete failed")
        }
    }

    func deleteAccount(token: String) async throws {
        var req = URLRequest(url: AppConfig.apiBaseURL.appendingPathComponent("/v1/me"))
        req.httpMethod = "DELETE"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (_, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw AppError.server("Delete account failed")
        }
    }

    func grantPro(userId: UUID, adminKey: String) async throws {
        var req = URLRequest(url: AppConfig.apiBaseURL.appendingPathComponent("/v1/admin/users/\(userId.uuidString)"))
        req.httpMethod = "PATCH"
        req.setValue(adminKey, forHTTPHeaderField: "X-API-Key")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["is_pro": true])
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw AppError.server(Self.errorMessage(from: data, fallback: "Grant Pro failed"))
        }
    }

    private func get<T: Decodable>(_ path: String, token: String) async throws -> T {
        var req = URLRequest(url: AppConfig.apiBaseURL.appendingPathComponent(path))
        req.httpMethod = "GET"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 120
        return try await perform(req)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B, token: String) async throws -> T {
        var req = URLRequest(url: AppConfig.apiBaseURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        req.timeoutInterval = 120
        return try await perform(req)
    }

    private func perform<T: Decodable>(_ req: URLRequest) async throws -> T {
        let startedAt = ContinuousClock.now
        let method = req.httpMethod ?? "GET"
        let path = req.url?.path ?? "unknown"
        AppLogger.api.info("request \(method, privacy: .public) \(path, privacy: .public)")

        do {
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw AppError.server("No response") }
        let elapsed = startedAt.duration(to: .now)
        AppLogger.api.info("response \(method, privacy: .public) \(path, privacy: .public) status=\(http.statusCode, privacy: .public) bytes=\(data.count, privacy: .public) elapsed=\(String(describing: elapsed), privacy: .public)")

        if http.statusCode == 401 { throw AppError.unauthorized }

        if http.statusCode == 403 {
            if let payload = try? decoder.decode(APIErrorPayload.self, from: data),
               let detail = payload.detail {
                throw AppError.quota(detail)
            }
            throw AppError.server(String(data: data, encoding: .utf8) ?? "Forbidden")
        }

        guard (200...299).contains(http.statusCode) else {
            throw AppError.server(Self.errorMessage(from: data, fallback: "HTTP \(http.statusCode)"))
        }

        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            AppLogger.api.error("decode failed \(path, privacy: .public): \(error.localizedDescription, privacy: .public)")
            throw AppError.server("Bad JSON: \(error.localizedDescription)")
        }
        } catch {
            let elapsed = startedAt.duration(to: .now)
            AppLogger.api.error("request failed \(method, privacy: .public) \(path, privacy: .public) elapsed=\(String(describing: elapsed), privacy: .public): \(error.localizedDescription, privacy: .public)")
            throw error
        }
    }

    private static func errorMessage(from data: Data, fallback: String) -> String {
        if let payload = try? JSONDecoder().decode(StringErrorPayload.self, from: data),
           !payload.detail.isEmpty {
            return payload.detail
        }
        return String(data: data, encoding: .utf8) ?? fallback
    }
}

private struct StringErrorPayload: Decodable {
    let detail: String
}
