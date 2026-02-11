// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "HideAndSeek",
    platforms: [
        .iOS(.v17),
    ],
    dependencies: [
        .package(url: "https://github.com/googlemaps/ios-maps-sdk", from: "9.0.0"),
    ],
    targets: [
        .target(
            name: "HideAndSeek",
            dependencies: [
                .product(name: "GoogleMaps", package: "ios-maps-sdk"),
            ],
            path: "HideAndSeek"
        ),
    ]
)
