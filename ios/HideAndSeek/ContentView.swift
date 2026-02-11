import GoogleMaps
import SwiftUI

private var hasGoogleMapsKey: Bool {
    if let apiKey = Bundle.main.infoDictionary?["GMSApiKey"] as? String,
       !apiKey.isEmpty, apiKey != "YOUR_GOOGLE_MAPS_API_KEY"
    {
        return true
    }
    return false
}

struct ContentView: View {
    var body: some View {
        ZStack {
            if hasGoogleMapsKey {
                GoogleMapView()
                    .ignoresSafeArea()
            } else {
                MapPlaceholderView()
            }

            VStack {
                Text("Hide & Seek")
                    .font(.largeTitle)
                    .fontWeight(.bold)
                    .padding()
                    .background(.ultraThinMaterial)
                    .cornerRadius(12)
                Spacer()
            }
            .padding(.top, 60)
        }
    }
}

struct GoogleMapView: UIViewRepresentable {
    func makeUIView(context: Context) -> GMSMapView {
        let options = GMSMapViewOptions()
        options.camera = GMSCameraPosition(
            latitude: 40.7128,
            longitude: -74.0060,
            zoom: 12.0
        )
        return GMSMapView(options: options)
    }

    func updateUIView(_ uiView: GMSMapView, context: Context) {}
}

struct MapPlaceholderView: View {
    var body: some View {
        ZStack {
            Color(.systemGray6)
                .ignoresSafeArea()
            VStack(spacing: 12) {
                Image(systemName: "map")
                    .font(.system(size: 64))
                    .foregroundStyle(.secondary)
                Text("Set GMSApiKey in Info.plist")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

#Preview {
    ContentView()
}
