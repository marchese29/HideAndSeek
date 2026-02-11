import GoogleMaps
import SwiftUI

@main
struct HideAndSeekApp: App {
    init() {
        if let apiKey = Bundle.main.infoDictionary?["GMSApiKey"] as? String,
           !apiKey.isEmpty, apiKey != "YOUR_GOOGLE_MAPS_API_KEY"
        {
            GMSServices.provideAPIKey(apiKey)
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
