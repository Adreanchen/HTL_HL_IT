package at.htlhl.weatherserver.controllers;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("weatherserver/greetings")
public class GreetingController {

    @GetMapping("/hello")
    @ResponseStatus(HttpStatus.OK)
    public ResponseEntity<String> sayHello(@RequestParam(defaultValue = "Hello World") String name) {
        if (!name.equalsIgnoreCase("Lieselotte")) {
            return new ResponseEntity<>(String.format("Hello %s!", name), HttpStatus.OK);
        } else {
            return new ResponseEntity<>(HttpStatus.NOT_FOUND);
        }
    }

    @GetMapping("/hello/{name}_{age}")
    @ResponseStatus(HttpStatus.OK)

    public String sayHelloAlternative(@PathVariable String name, @PathVariable Integer age) {
        return String.format("Hello %s! (age: %d", name, age);
    }
}
