package at.htlhl.httpclientdemo;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;

/**
 * Demonstrates how to use the HttpClient
 * to send a GET request to a specified URL and print the response.
 *
 * @author WIH
 */
public class HttpGetDemo {

    public static void main(String[] args) {
        new HttpGetDemo();
    }

    // Fields *****************************************************************

    private ObjectMapper jsonMapper = new ObjectMapper();

    // Constants **************************************************************

    private static final String PRODUCT_URI = "https://api.predic8.de/shop/v2/products?limit=1000&sort=name&order=asc";

    public HttpGetDemo() {
        try {

            /**
             * HTTP GET-Request erzeugen
             */
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(new URI(PRODUCT_URI))
                    .header("Content-Type", "application/json")
                    .GET()
                    .build();

            /**
             * Den erzeugten HTTP-Request mit HttpClient senden
             */
            HttpClient httpClient = HttpClient.newHttpClient();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

            /**
             * Die Rückmeldung verarbeiten: Status Code ok?
             * Inhalt mit Jackson in Product-Objekte umwandeln und ausgeben
             */
            if (response.statusCode() == HttpURLConnection.HTTP_OK) {

                // JSON-String in ProductResponse parsen
                ProductResponse productResponse = jsonMapper.readValue(response.body(), ProductResponse.class);

                // Produktliste extrahieren
                List<Product> products = productResponse.getProducts();

                // Jedes Produkt in der Schleife ausgeben
                for (Product p : products) {
                    System.out.println(p);
                }

            } else {
                System.err.println("HTTP-Request failed with status code: " + response.statusCode());
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