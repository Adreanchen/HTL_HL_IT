package at.htlhl.httpclientdemo;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

/**
 * Demonstrates how to use the HttpClient
 * to send a POST request with a JSON payload to a specified URL and handle the
 * response.
 *
 * @author FRITZ
 */
public class HttpPostDemo {

    public static void main(String[] args) {
        new HttpPostDemo();
    }

    // Fields *****************************************************************

    private ObjectMapper jsonMapper = new ObjectMapper();

    // Constants **************************************************************

    private static final String PRODUCT_URI = "https://api.predic8.de/shop/v2/products";

    public HttpPostDemo() {
        try {
            // Zu sendendes Produktobjekt erstellen
            Product newProduct = new Product();
            newProduct.setName("Benni");
            newProduct.setPrice(6.7);

            // Objekt in JSON-String serialisieren
            String requestBody = jsonMapper.writeValueAsString(newProduct);

            /**
             * HTTP POST-Request erzeugen
             */
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(new URI(PRODUCT_URI))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                    .build();

            /**
             * Den erzeugten HTTP-Request mit HttpClient senden
             */
            HttpClient httpClient = HttpClient.newHttpClient();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

            /**
             * Die Rückmeldung verarbeiten: Status Code prüfen (200 OK oder 201 Created)
             */
            if (response.statusCode() == HttpURLConnection.HTTP_CREATED
                    || response.statusCode() == HttpURLConnection.HTTP_OK) {

                // Erstelltes Produkt aus der Antwort parsen
                Product createdProduct = jsonMapper.readValue(response.body(), Product.class);

                System.out.println("Produkt erfolgreich angelegt:");
                System.out.println(createdProduct);

            } else {
                System.err.println("HTTP-Request failed with status code: " + response.statusCode());
                System.err.println("Response body: " + response.body());
                System.err.println("Program will exit.");
                System.exit(4);
            }

        } catch (URISyntaxException urisex) {
            System.err.println("Invalid URI: " + urisex.getMessage());
            System.err.println("Program will exit.");
            System.exit(1);
        } catch (IOException ioex) {
            System.err.println("IO Error: " + ioex.getMessage());
            System.err.println("Program will exit.");
            System.exit(2);
        } catch (InterruptedException iex) {
            System.err.println("Interrupted: " + iex.getMessage());
            System.err.println("Program will exit.");
            System.exit(3);
        }
    }
}