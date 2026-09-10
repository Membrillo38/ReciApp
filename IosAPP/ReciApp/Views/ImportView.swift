import SwiftUI

struct ImportView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Add recipe")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                    .foregroundStyle(ReciTheme.ink)

                Spacer(minLength: 0)

                Button {
                    ReciHaptics.lightImpact()
                    dismiss()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(ReciTheme.ink.opacity(0.62))
                        .frame(width: 42, height: 42)
                        .background(ReciTheme.surface, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
            }
            .padding(.bottom, 26)

            HStack(alignment: .center, spacing: 16) {
                ZStack {
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .fill(ReciTheme.orangeSoft)
                        .frame(width: 72, height: 72)
                    Image(systemName: "link")
                        .font(.system(size: 27, weight: .semibold))
                        .foregroundStyle(ReciTheme.orange)
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text("Paste recipe links")
                        .font(.title3.weight(.bold))
                        .foregroundStyle(ReciTheme.ink)
                    Text("Paste one or more TikTok, Instagram, YouTube, or Facebook links. We’ll queue them and import one at a time.")
                        .font(.subheadline)
                        .foregroundStyle(ReciTheme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: 22)

            Button {
                ReciHaptics.mediumImpact()
                Task {
                    dismiss()
                    await app.pasteAndImport()
                }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "doc.on.clipboard.fill")
                    Text("Paste from Clipboard")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .frame(height: 58)
                .foregroundStyle(.white)
                .background(ReciTheme.orange, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(app.isLoading)
            .opacity(app.isLoading ? 0.55 : 1)

            Text("TikTok  ·  Instagram  ·  YouTube  ·  Facebook")
                .font(.caption.weight(.medium))
                .foregroundStyle(ReciTheme.muted)
                .frame(maxWidth: .infinity)
                .padding(.top, 12)

            Text("You can also use Share → ReciApp from any video.")
                .font(.caption)
                .foregroundStyle(ReciTheme.muted.opacity(0.9))
                .frame(maxWidth: .infinity)
                .multilineTextAlignment(.center)
                .padding(.top, 5)
        }
        .padding(.horizontal, 24)
        .padding(.top, 16)
        .padding(.bottom, 20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ReciTheme.canvas.ignoresSafeArea())
    }
}
