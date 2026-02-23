# Integration: PlantUML (UML Diagrams)

* **Run the local server (Docker):**

  ```bash
  docker run -d --name plantuml -p 8080:8080 plantuml/plantuml-server
  ```

  Health check: `curl http://localhost:8080/` → should return HTML.

* **Point RAG to the server:** add to `config.json`

  ```json
  "plantuml_server": "http://localhost:8080"
  ```

* **How it’s used:** when the **Ada Lovelace** diagrammer is selected, the system generates `.puml` files **and** an **Open UML Diagram** link that renders through your PlantUML server. If the server isn’t running or the URL is wrong, the link won’t render.

* **Notes/Troubleshooting:**

  * Change the URL if your server runs elsewhere (e.g., a VM or remote host).
  * On WSL, `http://localhost:8080` works from Windows if the container publishes to that port.
  * Port already in use? Pick another, e.g.:

    ```bash
    docker run -d --name plantuml -p 8081:8080 plantuml/plantuml-server
    ```

    and set `"plantuml_server": "http://localhost:8081"`.
