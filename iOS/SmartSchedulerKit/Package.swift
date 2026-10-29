// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SmartSchedulerKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "SmartSchedulerKit", targets: ["SmartSchedulerKit"]),
    ],
    targets: [
        .target(name: "SmartSchedulerKit"),
        .testTarget(name: "SmartSchedulerKitTests", dependencies: ["SmartSchedulerKit"]),
    ]
)
