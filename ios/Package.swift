// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "HideAndSeek",
    platforms: [
        .iOS(.v17),
    ],
    dependencies: [
        .package(url: "https://github.com/nicklama/google-maps-ios-sdk-spm", from: "9.0.0"),
    ],
    targets: [
        .target(
            name: "HideAndSeek",
            dependencies: [
                .product(name: "GoogleMaps", package: "google-maps-ios-sdk-spm"),
            ],
            path: "HideAndSeek"
        ),
    ]
)
