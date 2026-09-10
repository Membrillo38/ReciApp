// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ClientStateHarness",
    platforms: [.macOS(.v13)],
    products: [.library(name: "ClientStateHarness", targets: ["ClientStateHarness"])],
    targets: [
        .target(name: "ClientStateHarness"),
        .testTarget(name: "ClientStateHarnessTests", dependencies: ["ClientStateHarness"]),
    ]
)
