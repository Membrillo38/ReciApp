import SwiftUI

struct ImportView: View {
    @EnvironmentObject private var app: AppViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Spacer()
                Button {
                    Task {
                        dismiss()
                        await app.pasteAndImport()
                    }
                } label: {
                    Label("Paste from Clipboard", systemImage: "doc.on.clipboard")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                }
                .buttonStyle(.borderedProminent)
                .disabled(app.isLoading)
                Spacer()
            }
            .padding(24)
            .navigationTitle("Add link")
        }
    }
}
