import SwiftUI

struct RecipeDetailView: View {
    @EnvironmentObject private var app: AppViewModel
    let recipe: RecipePublic
    @State private var showNewCategory = false
    @State private var newCategoryName = ""

    var body: some View {
        List {
            Section("Meta") {
                Text("title: \(recipe.title)")
                Text("id: \(recipe.id.uuidString)")
                Text("platform: \(recipe.platform)")
                Text("author: \(recipe.author ?? "—")")
                Text("servings: \(recipe.servings.map(String.init) ?? "—")")
                Text("prep: \(recipe.prepMinutes.map { "\($0)m" } ?? "—")")
                Text("cook: \(recipe.cookMinutes.map { "\($0)m" } ?? "—")")
                Text("source: \(recipe.sourceUrl)")
                if let thumb = recipe.thumbnailUrl { Text("thumb: \(thumb)") }
                if let desc = recipe.description { Text("desc: \(desc)") }
                if !recipe.tags.isEmpty { Text("tags: \(recipe.tags.joined(separator: ", "))") }
            }
            Section("Ingredients") {
                ForEach(recipe.ingredients) { ing in
                    Text(line(ing))
                }
            }
            Section("Steps") {
                ForEach(recipe.steps.sorted(by: { $0.order < $1.order })) { step in
                    VStack(alignment: .leading) {
                        Text("\(step.order). \(step.text)")
                        if let m = step.durationMinutes {
                            Text("(\(m) min)").font(.caption)
                        }
                    }
                }
            }
            if let url = URL(string: recipe.sourceUrl) {
                Section {
                    Link("Open source", destination: url)
                }
            }
        }
        .navigationTitle(recipe.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    ForEach(app.allCategoryNames, id: \.self) { category in
                        Button {
                            app.setCategory(category, for: recipe.id)
                        } label: {
                            if app.category(for: recipe.id) == category {
                                Label(category, systemImage: "checkmark")
                            } else {
                                Text(category)
                            }
                        }
                    }
                    Divider()
                    Button {
                        showNewCategory = true
                    } label: {
                        Label("New category", systemImage: "folder.badge.plus")
                    }
                } label: {
                    Image(systemName: "folder")
                }
                .accessibilityLabel("Category")
            }
        }
        .alert("New category", isPresented: $showNewCategory) {
            TextField("Name", text: $newCategoryName)
            Button("Save") {
                app.setCategory(newCategoryName, for: recipe.id)
                newCategoryName = ""
            }
            Button("Cancel", role: .cancel) {
                newCategoryName = ""
            }
        }
    }

    private func line(_ ing: Ingredient) -> String {
        [ing.quantity, ing.unit, ing.name]
            .compactMap { $0 }
            .filter { $0 != "null" }
            .joined(separator: " ")
    }
}
