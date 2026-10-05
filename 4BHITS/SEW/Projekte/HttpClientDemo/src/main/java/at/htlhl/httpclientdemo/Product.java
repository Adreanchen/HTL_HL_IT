package at.htlhl.httpclientdemo;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * POJO for product
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class Product {

    // Fields *****************************************************************

    private Integer id;
    private String name;
    private Double price;
    private String self_link;

    // Constructors ***********************************************************

    public Product() {

    }

    // Getters and Setters ****************************************************

    public Integer getId() {
        return id;
    }

    public void setId(Integer id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public Double getPrice() {
        return price;
    }

    public void setPrice(Double price) {
        this.price = price;
    }

    public String getSelf_link() {
        return self_link;
    }

    public void setSelf_link(String self_link) {
        this.self_link = self_link;
    }

    // toString für schöne Konsolenausgabe ************************************

    @Override
    public String toString() {
        return "Product{" +
                "id=" + id +
                ", name='" + name + '\'' +
                ", self_link='" + self_link + '\'' +
                '}';
    }
}