import ImageIO
import SwiftUI
import UIKit

struct RecipeCarouselView: View {
    let images: [URL]
    let height: CGFloat
    let fallback: Color
    @State private var selectedIndex = 0

    init(images: [URL], height: CGFloat = 360, fallback: Color = ReciTheme.orangeSoft) {
        self.images = images
        self.height = height
        self.fallback = fallback
    }

    var body: some View {
        if images.count > 1 {
            TabView(selection: $selectedIndex) {
                ForEach(Array(images.enumerated()), id: \.offset) { index, url in
                    slide(url: url, index: index)
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .automatic))
            .frame(height: height)
            .accessibilityLabel("Recipe image carousel")
            .onChange(of: images) { oldImages, newImages in
                selectedIndex = oldImages == newImages
                    ? min(selectedIndex, max(newImages.count - 1, 0))
                    : 0
            }
        } else if let url = images.first {
            slide(url: url, index: 0)
                .frame(height: height)
        } else {
            fallbackView
                .frame(height: height)
        }
    }

    private func slide(url: URL, index: Int) -> some View {
        DownsampledRecipeImage(
            url: url,
            isEnabled: images.count <= 1 || abs(index - selectedIndex) <= 1,
            fallback: fallback
        )
        .accessibilityLabel("Recipe image \(index + 1) of \(images.count)")
    }

    private var fallbackView: some View {
        ZStack {
            fallback
            Image(systemName: "fork.knife")
                .font(.system(size: 42, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
        }
    }
}

private struct DownsampledRecipeImage: View {
    let url: URL
    let isEnabled: Bool
    let fallback: Color
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                fallbackView
            }
        }
        .frame(maxWidth: .infinity)
        .clipped()
        .id(url)
        .task(id: "\(url.absoluteString)-\(isEnabled)") {
            guard isEnabled, image == nil else { return }
            for attempt in 0..<2 {
                guard !Task.isCancelled else { return }
                if let loaded = await Self.load(url: url, maxPixelSize: 1800) {
                    image = loaded
                    return
                }
                if attempt == 0 {
                    try? await Task.sleep(for: .milliseconds(250))
                }
            }
        }
    }

    private var fallbackView: some View {
        ZStack {
            fallback
            Image(systemName: "fork.knife")
                .font(.system(size: 42, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
        }
    }

    private static func load(url: URL, maxPixelSize: Int) async -> UIImage? {
        if let cached = RecipeImageCache.shared.image(for: url) {
            return cached
        }

        var request = URLRequest(url: url)
        request.cachePolicy = .returnCacheDataElseLoad
            request.timeoutInterval = 12
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                return nil
            }
            guard let source = CGImageSourceCreateWithData(data as CFData, nil) else {
                return nil
            }
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: maxPixelSize,
            ]
            guard let cgImage = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
                return nil
            }
            let result = UIImage(cgImage: cgImage)
            RecipeImageCache.shared.insert(result, for: url)
            return result
        } catch {
            return nil
        }
    }
}

private final class RecipeImageCache {
    static let shared = RecipeImageCache()
    private let cache = NSCache<NSURL, UIImage>()

    func image(for url: URL) -> UIImage? {
        cache.object(forKey: url as NSURL)
    }

    func insert(_ image: UIImage, for url: URL) {
        cache.setObject(image, forKey: url as NSURL)
    }
}
