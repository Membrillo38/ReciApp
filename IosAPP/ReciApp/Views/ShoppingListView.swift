import SwiftUI

struct ShoppingListView: View {
    @EnvironmentObject private var app: AppViewModel
    @EnvironmentObject private var auth: AuthService
    @Environment(\.dismiss) private var dismiss
    @State private var items: [ShoppingListItem] = []
    @State private var mode: Mode = .byRecipe

    private enum Mode: String, CaseIterable, Identifiable {
        case byRecipe
        case together

        var id: String { rawValue }

        var title: String {
            switch self {
            case .byRecipe: return ReciLocalization.string("By recipe")
            case .together: return ReciLocalization.string("Together")
            }
        }
    }

    private var userID: String {
        auth.session?.user.id.uuidString ?? "anonymous"
    }

    private var groupedByRecipe: [(title: String, items: [ShoppingListItem])] {
        var order: [String] = []
        var map: [String: [ShoppingListItem]] = [:]
        for item in items {
            if map[item.recipeTitle] == nil {
                order.append(item.recipeTitle)
                map[item.recipeTitle] = []
            }
            map[item.recipeTitle, default: []].append(item)
        }
        return order.map { (title: $0, items: map[$0] ?? []) }
    }

    private var mergedItems: [MergedShoppingItem] {
        ShoppingListStore.merged(from: items)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("", selection: $mode) {
                    ForEach(Mode.allCases) { option in
                        Text(option.title).tag(option)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, 12)

                if items.isEmpty {
                    emptyState
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 16) {
                            switch mode {
                            case .byRecipe:
                                ForEach(groupedByRecipe, id: \.title) { group in
                                    recipeGroup(title: group.title, items: group.items)
                                }
                            case .together:
                                togetherList
                            }
                        }
                        .padding(.horizontal, 20)
                        .padding(.bottom, 28)
                    }
                }
            }
            .background(ReciTheme.canvas.ignoresSafeArea())
            .navigationTitle(ReciLocalization.string("Shopping list"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(ReciLocalization.string("Close")) {
                        ReciHaptics.lightImpact()
                        dismiss()
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if items.contains(where: \.isChecked) {
                        Button(ReciLocalization.string("Clear checked")) {
                            ReciHaptics.selection()
                            ShoppingListStore.clearChecked(for: userID)
                            reload()
                        }
                    }
                }
            }
            .onAppear(perform: reload)
            .animation(.spring(response: 0.36, dampingFraction: 0.86), value: mode)
            .animation(.spring(response: 0.36, dampingFraction: 0.86), value: items.count)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "cart")
                .font(.system(size: 36, weight: .semibold))
                .foregroundStyle(ReciTheme.orange)
            Text(ReciLocalization.string("No ingredients yet"))
                .font(.headline)
                .foregroundStyle(ReciTheme.ink)
            Text(ReciLocalization.string("Add ingredients from a recipe to build your list."))
                .font(.subheadline)
                .foregroundStyle(ReciTheme.muted)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func recipeGroup(title: String, items: [ShoppingListItem]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(ReciTheme.ink)
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    shoppingRow(
                        title: itemLine(item),
                        isChecked: item.isChecked,
                        onToggle: {
                            ShoppingListStore.toggle(id: item.id, for: userID)
                            reload()
                        },
                        onDelete: {
                            ShoppingListStore.remove(id: item.id, for: userID)
                            reload()
                        }
                    )
                    if index < items.count - 1 {
                        Divider().padding(.leading, 44)
                    }
                }
            }
            .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
    }

    private var togetherList: some View {
        VStack(spacing: 0) {
            ForEach(Array(mergedItems.enumerated()), id: \.element.id) { index, item in
                shoppingRow(
                    title: mergedLine(item),
                    subtitle: item.sourceTitles.count > 1 ? item.sourceTitles.joined(separator: " · ") : nil,
                    isChecked: item.isChecked,
                    onToggle: {
                        ShoppingListStore.toggleMerged(ids: item.sourceIDs, for: userID)
                        reload()
                    },
                    onDelete: {
                        ShoppingListStore.remove(ids: item.sourceIDs, for: userID)
                        reload()
                    }
                )
                if index < mergedItems.count - 1 {
                    Divider().padding(.leading, 44)
                }
            }
        }
        .background(ReciTheme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private func shoppingRow(
        title: String,
        subtitle: String? = nil,
        isChecked: Bool,
        onToggle: @escaping () -> Void,
        onDelete: @escaping () -> Void
    ) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Button(action: {
                ReciHaptics.selection()
                onToggle()
            }) {
                Image(systemName: isChecked ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(isChecked ? ReciTheme.green : ReciTheme.muted)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(isChecked ? ReciTheme.muted : ReciTheme.ink)
                    .strikethrough(isChecked)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(ReciTheme.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            Button(action: {
                ReciHaptics.warning()
                onDelete()
            }) {
                Image(systemName: "trash")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(ReciTheme.muted)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(ReciLocalization.string("Delete"))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
    }

    private func itemLine(_ item: ShoppingListItem) -> String {
        [item.quantity, item.unit, item.name]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private func mergedLine(_ item: MergedShoppingItem) -> String {
        [item.quantity, item.unit, item.name]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private func reload() {
        items = ShoppingListStore.load(for: userID)
    }
}
