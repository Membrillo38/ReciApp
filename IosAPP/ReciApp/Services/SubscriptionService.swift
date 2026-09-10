import Foundation
import SuperwallKit

@MainActor
final class SubscriptionService {
    static let shared = SubscriptionService()

    private var configured = false
    private var identifiedUserID: String?

    private init() {}

    var onEntitlementChange: (() -> Void)?

    func configure() {
        guard !configured else { return }
        Superwall.configure(apiKey: AppConfig.superwallPublicKey)
        Superwall.shared.delegate = self
        configured = true
    }

    func identify(userID: UUID) {
        configure()
        let value = userID.uuidString
        guard identifiedUserID != value else { return }
        Superwall.shared.identify(userId: value)
        Superwall.shared.setUserAttributes(["supabase_user_id": value])
        identifiedUserID = value
    }

    func reset() {
        guard configured, identifiedUserID != nil else { return }
        Superwall.shared.reset()
        identifiedUserID = nil
    }

    func presentUpgrade(onFinished: (() -> Void)? = nil) {
        configure()
        Superwall.shared.register(placement: "free_limit_reached") {
            onFinished?()
        }
    }

    func restorePurchases(onFinished: @escaping (Bool) -> Void) {
        configure()
        Task { @MainActor in
            let result = await Superwall.shared.restorePurchases()
            switch result {
            case .restored:
                onFinished(true)
                onEntitlementChange?()
            case .failed(_):
                onFinished(false)
            }
        }
    }
}

extension SubscriptionService: SuperwallDelegate {
    func subscriptionStatusDidChange(
        from oldValue: SubscriptionStatus,
        to newValue: SubscriptionStatus
    ) {
        guard oldValue != newValue else { return }
        onEntitlementChange?()
    }

    func didDismissPaywall(withInfo paywallInfo: PaywallInfo) {
        onEntitlementChange?()
    }
}
