import SwiftUI

struct ProfileView: View {
    @EnvironmentObject private var auth: AuthService
    @EnvironmentObject private var app: AppViewModel
    @State private var confirmDelete = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Account") {
                    if let me = app.me {
                        Text("id: \(me.id.uuidString)")
                        Text("plan: \(app.planLabel)")
                        Text("free: \(me.freeUsedThisWeek)/\(me.freeLimit) (left \(me.freeRemaining))")
                        Text("is_pro: \(me.isPro ? "yes" : "no")")
                        if let exp = me.proExpiresAt { Text("pro_expires: \(exp)") }
                        if let rem = me.proRemainingCents { Text("fair_use_left: \(Int(rem))c") }
                    } else {
                        Text("not loaded")
                    }
                }
                Section("Dev") {
                    Text("superwall: off")
                    Text("autoGrantPro: \(DevConfig.autoGrantPro ? "on" : "off")")
                    Text("adminKey: \(Secrets.adminApiKey != nil ? "set" : "missing")")
                }
                Section {
                    Button("Refresh") { Task { await app.refreshAll() } }
                    Button("Sign out") { Task { await auth.signOut() } }
                    Button("Delete account", role: .destructive) { confirmDelete = true }
                }
                if let err = app.errorMessage {
                    Section("Error") { Text(err) }
                }
            }
            .navigationTitle("Profile")
            .alert("Delete account?", isPresented: $confirmDelete) {
                Button("Delete", role: .destructive) { Task { await app.deleteAccount() } }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
