import Foundation
import OSLog

enum AppLogger {
    static let api = Logger(subsystem: "com.membri.reciapp", category: "api")
    static let auth = Logger(subsystem: "com.membri.reciapp", category: "auth")
    static let app = Logger(subsystem: "com.membri.reciapp", category: "app")
}

final class ReciNoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

final class APIClient: @unchecked Sendable {
    typealias TokenProvider = @Sendable (_ refresh: Bool) async throws -> String

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    private let baseURL = AppConfig.apiBaseURL
    private let redirectGuard = ReciNoRedirectDelegate()
    private let session: URLSession
    private let tokenProvider: TokenProvider?

    init(
        session: URLSession? = nil,
        tokenProvider: TokenProvider? = nil
    ) {
        self.tokenProvider = tokenProvider
        if let session {
            self.session = session
        } else {
            self.session = URLSession(
                configuration: .default,
                delegate: redirectGuard,
                delegateQueue: nil
            )
        }
    }

    static func warmUpBackend() async {
        let client = APIClient()
        var request = URLRequest(url: AppConfig.apiBaseURL.appending(path: "health"))
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        _ = try? await client.perform(request, retrySafe: true) as HealthResponse
    }

    func me() async throws -> MeResponse {
        try await request("v1/me")
    }

    func myRecipes(language: String) async throws -> [RecipeSummary] {
        let response: RecipeListResponse = try await request("v1/me/recipes", language: language)
        return response.items
    }

    func recipe(id: UUID, language: String) async throws -> RecipePublic {
        try await request("v1/recipes/\(id.uuidString)", language: language)
    }

    func extract(url: String, language: String) async throws -> ExtractJobResponse {
        let body = try encoder.encode(ExtractRequest(url: url, language: language))
        return try await request("v1/extract", method: "POST", body: body, retrySafe: false)
    }

    func myJobs() async throws -> QueuedJobsResponse {
        try await request("v1/me/jobs")
    }

    func job(id: UUID, language: String) async throws -> JobResponse {
        try await request("v1/jobs/\(id.uuidString)", language: language, retrySafe: false)
    }

    func removeRecipe(id: UUID) async throws -> OkResponse {
        try await request("v1/me/recipes/\(id.uuidString)", method: "DELETE", retrySafe: false)
    }

    func deleteAccount() async throws -> OkResponse {
        try await request("v1/me", method: "DELETE", retrySafe: false)
    }

    func waitForRecipe(
        jobID: UUID,
        language: String,
        onUpdate: @Sendable (JobResponse) async -> Void = { _ in }
    ) async throws -> RecipePublic {
        var currentID = jobID
        let deadline = ContinuousClock.now.advanced(by: .seconds(600))
        while ContinuousClock.now < deadline {
            try Task.checkCancellation()
            do {
                let state = try await job(id: currentID, language: language)
                await onUpdate(state)
                currentID = JobFollowPolicy.persistedID(jobID: state.jobId, nextJobID: state.nextJobId)
                switch JobFollowPolicy.outcome(status: state.status, hasRecipe: state.recipe != nil) {
                case .failed:
                    throw AppError.jobFailed(state.error ?? "Import failed")
                case .succeeded:
                    if let recipe = state.recipe { return recipe }
                case .wait:
                    break
                case .invalid:
                    throw URLError(.cannotParseResponse)
                }
            } catch let error as AppError {
                switch error {
                case .rateLimited(_, let retryAfter):
                    try await Task.sleep(for: .seconds(RetryAfterPolicy.delaySeconds(retryAfter: retryAfter)))
                    continue
                case .unavailable, .transient:
                    try await Task.sleep(for: .seconds(2))
                    continue
                default:
                    throw error
                }
            } catch let error as URLError {
                guard ImportJobRetentionPolicy.shouldRetainURLError(error.code) else { throw error }
                try await Task.sleep(for: .seconds(2))
                continue
            }
            try await Task.sleep(for: .seconds(2))
        }
        throw URLError(.timedOut)
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        language: String? = nil,
        body: Data? = nil,
        retrySafe: Bool = true
    ) async throws -> T {
        let url = makeURL(path, language: language)
        for attempt in 0...1 {
            try Task.checkCancellation()
            var request = URLRequest(url: url)
            request.httpMethod = method
            request.timeoutInterval = 90
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            if body != nil {
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            }
            let token = try await token(refresh: attempt == 1)
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            do {
                return try await perform(request, retrySafe: retrySafe && attempt == 0)
            } catch let error as AppError {
                if case .unauthorized = error, attempt == 0 { continue }
                throw error
            }
        }
        throw AppError.unauthorized
    }

    private func token(refresh: Bool) async throws -> String {
        guard let tokenProvider else { throw AppError.unauthorized }
        return try await tokenProvider(refresh)
    }

    private func makeURL(_ path: String, language: String?) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.path = path.hasPrefix("/") ? path : "/" + path
        if let language {
            components.queryItems = [URLQueryItem(name: "language", value: language)]
        }
        return components.url!
    }

    private func perform<T: Decodable>(_ request: URLRequest, retrySafe: Bool) async throws -> T {
        var request = request
        let requestID = UUID().uuidString
        request.setValue(requestID, forHTTPHeaderField: "X-Request-ID")
        var lastError: Error?
        let maximumAttempts = retrySafe
            ? RequestRetryPolicy.maximumAttempts(method: request.httpMethod ?? "GET")
            : 1
        for retry in 0..<maximumAttempts {
            do {
                return try await performOnce(request, attempt: retry + 1, requestID: requestID)
            } catch let error as AppError {
                guard error.isTransient, retry + 1 < maximumAttempts else { throw error }
                lastError = error
                if case .rateLimited(_, let retryAfter) = error {
                    try await Task.sleep(for: .seconds(RetryAfterPolicy.delaySeconds(retryAfter: retryAfter)))
                    continue
                }
            } catch let error as URLError {
                guard Self.isRetryable(error), retry + 1 < maximumAttempts else { throw error }
                lastError = error
            }
            AppLogger.api.warning("retry requestId=\(requestID, privacy: .public) attempt=\(retry + 2, privacy: .public)")
            let baseNanoseconds = UInt64(retry + 1) * 500_000_000
            let jitterNanoseconds = UInt64.random(in: 0...250_000_000)
            try await Task.sleep(nanoseconds: baseNanoseconds + jitterNanoseconds)
        }
        throw lastError ?? AppError.server("Request failed")
    }

    private func performOnce<T: Decodable>(
        _ request: URLRequest,
        attempt: Int,
        requestID: String
    ) async throws -> T {
        let startedAt = ContinuousClock.now
        let method = request.httpMethod ?? "GET"
        let path = request.url?.path ?? "unknown"
        AppLogger.api.info("request \(method, privacy: .public) \(path, privacy: .public) requestId=\(requestID, privacy: .public) attempt=\(attempt, privacy: .public)")

        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw AppError.server("No response") }
            let elapsed = startedAt.duration(to: .now)
            let correlationID = http.value(forHTTPHeaderField: "X-Correlation-ID") ?? "missing"
            AppLogger.api.info("response \(method, privacy: .public) \(path, privacy: .public) status=\(http.statusCode, privacy: .public) bytes=\(data.count, privacy: .public) elapsed=\(String(describing: elapsed), privacy: .public) requestId=\(requestID, privacy: .public) correlationId=\(correlationID, privacy: .public)")

            if http.statusCode == 401 { throw AppError.unauthorized }
            guard (200...299).contains(http.statusCode) else {
                throw Self.mappedError(
                    status: http.statusCode,
                    data: data,
                    retryAfter: http.value(forHTTPHeaderField: "Retry-After")
                )
            }

            do {
                return try decoder.decode(T.self, from: data)
            } catch {
                AppLogger.api.error("decode failed \(path, privacy: .public): \(error.localizedDescription, privacy: .public)")
                throw AppError.server("Bad JSON: \(error.localizedDescription)")
            }
        } catch {
            let elapsed = startedAt.duration(to: .now)
            AppLogger.api.error("request failed \(method, privacy: .public) \(path, privacy: .public) elapsed=\(String(describing: elapsed), privacy: .public) requestId=\(requestID, privacy: .public): \(error.localizedDescription, privacy: .public)")
            throw error
        }
    }

    private static func mappedError(status: Int, data: Data, retryAfter: String?) -> AppError {
        if status == 403, let payload = try? JSONDecoder().decode(APIErrorPayload.self, from: data),
           let detail = payload.detail {
            switch APIErrorBehavior.action(status: status, code: detail.code) {
            case .presentPaywall:
                return .quota(detail)
            case .showFairUse:
                return .fairUse(detail.message)
            default:
                return .forbidden(detail.message)
            }
        }

        let parsed = APIErrorDetailParser.parse(data: data, status: status)
        switch APIErrorBehavior.action(status: status, code: parsed.code) {
        case .reauthenticate:
            return .unauthorized
        case .presentPaywall:
            return .quota(
                QuotaErrorDetail(code: parsed.code ?? "FREE_WEEKLY_LIMIT", message: parsed.message, freeUsedThisWeek: nil, freeLimit: nil)
            )
        case .showFairUse:
            return .fairUse(parsed.message)
        case .showForbidden:
            return .forbidden(parsed.message)
        case .showNotFound:
            return .notFound(parsed.message)
        case .correctInput:
            return .invalidInput(parsed.message)
        case .waitAndRetry:
            return .rateLimited(parsed.message, retryAfter: retryAfter)
        case .keepDataAndRetry:
            return status == 503 ? .unavailable(parsed.message) : .transient(parsed.message)
        case .showJobFailure:
            return .jobFailed(parsed.message)
        case .showGeneric:
            return .server(parsed.message)
        }
    }

    private static func isRetryable(_ error: URLError) -> Bool {
        ImportJobRetentionPolicy.shouldRetainURLError(error.code)
    }
}
