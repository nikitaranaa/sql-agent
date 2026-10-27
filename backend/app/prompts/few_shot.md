Examples (question -> SQL) for this schema:

Q: Show all employees hired after January 2024.
SQL: SELECT * FROM Employees WHERE HireDate >= '2024-01-01';

Q: How many customers are there in each state?
SQL: SELECT State, COUNT(*) AS CustomerCount FROM Customers GROUP BY State ORDER BY CustomerCount DESC;

Q: List orders with the customer's full name.
SQL: SELECT o.OrderID, o.OrderDate, c.FirstName || ' ' || c.LastName AS CustomerName, o.TotalAmount
FROM Orders AS o
JOIN Customers AS c ON c.CustomerID = o.CustomerID
ORDER BY o.OrderDate DESC;

Q: Top 5 customers by total revenue.
SQL: SELECT c.CustomerID, c.FirstName, c.LastName, SUM(o.TotalAmount) AS Revenue
FROM Customers AS c
JOIN Orders AS o ON o.CustomerID = c.CustomerID
WHERE o.Status <> 'Cancelled'
GROUP BY c.CustomerID, c.FirstName, c.LastName
ORDER BY Revenue DESC
LIMIT 5;

Q: Which products have never been ordered?
SQL: SELECT p.ProductID, p.Name FROM Products AS p
LEFT JOIN OrderItems AS oi ON oi.ProductID = p.ProductID
WHERE oi.OrderItemID IS NULL;

Q: Monthly revenue in 2025.
SQL: SELECT strftime('%Y-%m', OrderDate) AS Month, ROUND(SUM(TotalAmount), 2) AS Revenue
FROM Orders
WHERE OrderDate >= '2025-01-01' AND OrderDate < '2026-01-01' AND Status <> 'Cancelled'
GROUP BY Month
ORDER BY Month;
