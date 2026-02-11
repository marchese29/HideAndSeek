import GoogleMaps
import SwiftUI

struct ContentView: View {
    var body: some View {
        ZStack {
            GoogleMapView()
                .ignoresSafeArea()

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

#Preview {
    ContentView()
}
