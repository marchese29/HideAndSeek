# iOS App — SwiftUI + Google Maps

iOS client for the HideAndSeek game, centered on a Google Maps interface.

## Build & Run

Open `HideAndSeek.xcodeproj` in Xcode and build (Cmd+B) / run (Cmd+R).

## Google Maps Setup

1. Get an API key from [Google Cloud Console](https://console.cloud.google.com/).
2. Enable "Maps SDK for iOS".
3. Replace `YOUR_GOOGLE_MAPS_API_KEY` in `HideAndSeek/Info.plist`.
4. Initialize the SDK in `HideAndSeekApp.swift`:
   ```swift
   GMSServices.provideAPIKey("YOUR_KEY")
   ```

## Project Structure

- `HideAndSeek/HideAndSeekApp.swift` — App entry point
- `HideAndSeek/ContentView.swift` — Main view with Google Maps
- `HideAndSeek/Info.plist` — App configuration
- `Package.swift` — SPM dependencies (Google Maps SDK)

## Dependencies

Managed via Swift Package Manager. The Google Maps iOS SDK is added through `Package.swift` and the Xcode project's package references.

## Conventions

- Target iOS 17+.
- Use SwiftUI for all new views.
- Use `UIViewRepresentable` to bridge Google Maps `GMSMapView` into SwiftUI.
