import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var app: AppViewModel
    @State private var showingSettings = false
    @State private var addExpanded = false

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottomLeading) {
                List {
                    if let err = app.errorMessage {
                        Text(err)
                            .foregroundStyle(.red)
                    }
                    if app.isLoading && app.recipes.isEmpty {
                        Text("Loading…")
                    }
                    if app.isImporting {
                        ProgressCard(progress: app.importProgress)
                            .listRowInsets(EdgeInsets(top: 12, leading: 16, bottom: 12, trailing: 16))
                            .listRowBackground(Color.clear)
                    }
                    ForEach(app.categoryCounts()) { category in
                        NavigationLink {
                            CategoryRecipesView(categoryName: category.name)
                        } label: {
                            Label {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(category.name)
                                    Text("\(category.count) recipe\(category.count == 1 ? "" : "s")")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            } icon: {
                                Image(systemName: "folder")
                                    .foregroundStyle(.yellow)
                            }
                        }
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture {
                    if addExpanded { withAnimation(.spring(response: 0.38, dampingFraction: 0.82)) { addExpanded = false } }
                }
                .refreshable { await app.refreshAll() }

                Button {
                    withAnimation(.spring(response: 0.38, dampingFraction: 0.82)) {
                        if addExpanded {
                            addExpanded = false
                            Task { await app.pasteAndImport() }
                        } else {
                            addExpanded = true
                        }
                    }
                } label: {
                    Group {
                        if addExpanded {
                            Label("Paste from Clipboard", systemImage: "doc.on.clipboard")
                                .font(.headline)
                        } else {
                            Image(systemName: "plus")
                                .font(.title2.weight(.semibold))
                        }
                    }
                    .frame(maxWidth: addExpanded ? .infinity : nil)
                    .frame(width: addExpanded ? nil : 56, height: 56)
                    .background(.tint)
                    .foregroundStyle(.white)
                    .clipShape(Capsule())
                    .shadow(radius: 4, y: 2)
                }
                .accessibilityLabel("Add link")
                .padding(.leading, 20)
                .padding(.bottom, 20)
            }
            .navigationTitle("Recipes")
            .navigationDestination(item: $app.selectedRecipe) { recipe in
                RecipeDetailView(recipe: recipe)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showingSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
            }
            .sheet(isPresented: $showingSettings) { ProfileView() }
        }
    }
}

private struct ProgressCard: View {
    let progress: Int

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.accentColor.opacity(0.12))
            GeometryReader { proxy in
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.accentColor.opacity(0.28))
                    .frame(height: proxy.size.height * CGFloat(min(max(progress, 0), 100)) / 100)
                    .animation(.easeInOut(duration: 0.45), value: progress)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            HStack {
                Image(systemName: "sparkles")
                Text("\(progress)%")
                    .monospacedDigit()
                    .fontWeight(.semibold)
                Spacer()
                Text("Importing")
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 16)
        }
        .frame(height: 80)
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .stroke(style: StrokeStyle(lineWidth: 1.5, dash: [7, 5]))
                .foregroundStyle(Color.accentColor.opacity(0.65))
        }
        .transition(.move(edge: .top).combined(with: .opacity))
        .animation(.spring(response: 0.45, dampingFraction: 0.82), value: progress)
    }
}

private struct CategoryRecipesView: View {
    @EnvironmentObject private var app: AppViewModel
    let categoryName: String

    var body: some View {
        List {
            ForEach(app.recipes(in: categoryName)) { item in
                Button {
                    Task { await app.openRecipe(item) }
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title)
                        Text("\(item.platform) · \(item.sourceUrl)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .onDelete { idx in
                let items = app.recipes(in: categoryName)
                for i in idx {
                    Task { await app.deleteRecipe(items[i]) }
                }
            }
        }
        .navigationTitle(categoryName)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await app.refreshAll() }
    }
}
