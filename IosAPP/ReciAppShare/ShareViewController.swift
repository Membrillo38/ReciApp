import UIKit
import UniformTypeIdentifiers

private enum ShareHaptics {
    static func lightImpact() {
        guard !UIAccessibility.isReduceMotionEnabled else { return }
        let generator = UIImpactFeedbackGenerator(style: .light)
        generator.prepare()
        generator.impactOccurred()
    }

    static func error() {
        guard !UIAccessibility.isReduceMotionEnabled else { return }
        let generator = UINotificationFeedbackGenerator()
        generator.prepare()
        generator.notificationOccurred(.error)
    }
}

final class ShareViewController: UIViewController {
    private var didStart = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground

        let label = UILabel()
        label.text = ReciLocalization.string("Opening ReciApp…")
        label.textAlignment = .center
        label.font = .preferredFont(forTextStyle: .headline)
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            label.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -24),
        ])
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        guard !didStart else { return }
        didStart = true

        Task { [weak self] in
            guard let self else { return }
            let sharedTexts = await self.sharedTexts()
            await MainActor.run {
                self.deliver(sharedTexts)
            }
        }
    }

    private func sharedTexts() async -> [String] {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem] else { return [] }
        var texts: [String] = []

        for item in items {
            for provider in item.attachments ?? [] {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
                   let value = await loadItem(provider, typeIdentifier: UTType.url.identifier),
                   let text = stringValue(value) {
                    texts.append(text)
                    continue
                }

                if provider.hasItemConformingToTypeIdentifier(UTType.text.identifier),
                   let value = await loadItem(provider, typeIdentifier: UTType.text.identifier),
                   let text = stringValue(value) {
                    texts.append(text)
                }
            }
        }
        return texts
    }

    private func loadItem(_ provider: NSItemProvider, typeIdentifier: String) async -> Any? {
        await withCheckedContinuation { continuation in
            provider.loadItem(forTypeIdentifier: typeIdentifier, options: nil) { item, _ in
                continuation.resume(returning: item)
            }
        }
    }

    private func stringValue(_ value: Any) -> String? {
        if let url = value as? URL { return url.absoluteString }
        if let url = value as? NSURL { return url.absoluteString }
        if let string = value as? String { return string }
        if let string = value as? NSString { return string as String }
        if let data = value as? Data { return String(data: data, encoding: .utf8) }
        return nil
    }

    private func deliver(_ rawValues: [String]) {
        let language = AppLanguageStore.current.serverCode
        var firstDelivery: ShareDelivery?
        var enqueued = 0

        for raw in rawValues {
            for url in URLNormalizer.normalizeAll(raw) {
                if let delivery = ShareInbox.enqueue(raw: url, language: language) {
                    enqueued += 1
                    if firstDelivery == nil { firstDelivery = delivery }
                }
            }
        }

        guard let firstDelivery, enqueued > 0 else {
            showError(ReciLocalization.string("No compatible link found. Share a TikTok, Instagram, YouTube, or Facebook video."))
            return
        }

        var components = URLComponents()
        components.scheme = "reciapp"
        components.host = "import"
        components.queryItems = [
            URLQueryItem(name: "url", value: firstDelivery.url),
            URLQueryItem(name: "id", value: firstDelivery.id.uuidString),
        ]

        guard let destination = components.url else {
            finishSuccessfully()
            return
        }

        extensionContext?.open(destination) { _ in }
        finishSuccessfully()
    }

    private func finishSuccessfully() {
        ShareHaptics.lightImpact()
        extensionContext?.completeRequest(returningItems: nil)
    }

    private func showError(_ message: String) {
        ShareHaptics.error()
        let alert = UIAlertController(title: "ReciApp", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: ReciLocalization.string("Close"), style: .default) { [weak self] _ in
            self?.extensionContext?.completeRequest(returningItems: nil)
        })
        present(alert, animated: true)
    }
}
