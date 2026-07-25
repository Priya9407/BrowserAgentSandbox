from app.agent.agent import BrowserAgent


def test_agent():

    agent = BrowserAgent()

    agent.set_task("Buy the laptop")

    dom = """
    <html>
        <body>
            <button id="buy">Buy Laptop</button>
        </body>
    </html>
    """

    action = agent.think(dom)

    print(action.model_dump())


if __name__ == "__main__":
    test_agent()
